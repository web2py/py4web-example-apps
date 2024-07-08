import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from importlib.machinery import SourceFileLoader

if __name__ != "__main__":
    import py4web
    import requests
    import selenium
    from bs4 import BeautifulSoup as Soup
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys


# The rest of the code except "dockerize" is intended to run in this image
DOCKERFILE = """
FROM python:3.11-alpine

# update apk repo
RUN echo "http://dl-4.alpinelinux.org/alpine/v3.14/main" >> /etc/apk/repositories 
RUN echo "http://dl-4.alpinelinux.org/alpine/v3.14/community" >> /etc/apk/repositories

# install chromedriver
RUN apk update
RUN apk add git
RUN apk add chromium
RUN apk add chromium-chromedriver

# upgrade pip
RUN python -m pip install --upgrade pip
RUN python -m pip install --upgrade requests
RUN python -m pip install --upgrade mechanize
RUN python -m pip install --upgrade BeautifulSoup4
RUN python -m pip install --upgrade selenium
RUN python -m pip install --upgrade py4web
RUN python -m pip install --upgrade edq-canvas

CMD ["python", "--version"]
"""

############################################################################
# Convenience functions
############################################################################


def run(cmd):
    """Log and run a command"""
    print("Running:", cmd)
    return (
        subprocess.run(cmd, check=True, capture_output=True, shell=True)
        .stdout.decode()
        .strip()
    )


def make_chrome_driver(headless=False):
    options = webdriver.ChromeOptions()
    service = Service("/usr/lib/chromium/chromedriver")
    options.binary_location = "/usr/lib/chromium/chromium"

    options.add_argument("--window-size=1024,768")
    options.add_argument("--disable-extensions")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--no-sandbox")
    if headless:
        options.add_argument("--headless")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--enable-automation")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-software-rasterizer")
    return webdriver.Chrome(options=options, service=service)


def find_repo_root(path):
    path = os.path.abspath(path)
    root = path
    while root:
        root = os.path.dirname(root)
        if os.path.exists(os.path.join(root, ".git")):
            break
    else:
        raise NotImplementedError("path but be in a repo")
    return root, os.path.relpath(path, root)


############################################################################
# Base Tester class
############################################################################


class StopTester(Exception):
    pass


class Tester:
    def __init__(self, headless=True, post_grade=None):
        """Creates a tester instance"""
        self._notifications = []
        self.browser = make_chrome_driver(headless)
        # the vars below are defined when py4web starts
        self.base_url = None
        self.app_as_module = None
        self.dest_apps = None
        self.post_grade = {}

    def start_py4web(self, path, port=8888, expect_db=True):
        """Starts py4web server and returns the base URL for the app"""
        source_apps, app_name = os.path.split(path)
        print("Starting the server")
        self.app_name = app_name
        self.dest_apps = os.path.join(tempfile.mkdtemp(), "apps")
        url = f"http://127.0.0.1:{port}/{app_name}/"
        shutil.rmtree(self.dest_apps, ignore_errors=True)
        if not os.path.exists(source_apps):
            print(f"{source_apps} does not exist!")
            self.stop()
        run(f"cp -r {source_apps} {self.dest_apps}")
        subprocess.run(
            ["rm", "-rf", os.path.join(self.dest_apps, app_name, "databases")]
        )
        self.server = None
        cmd = f"py4web run {self.dest_apps} --port={port} --app_names={app_name}"
        print("Running:", cmd)
        try:
            self.server = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except Exception:
            print("Unable to start py4web")
            self.stop()
        started = False
        while True:
            self.server.stdout.flush()
            line = self.server.stdout.readline().decode().rstrip()
            print(line)
            if "[X]" in line:
                started = True
            if "127.0.0.1:" in line:
                break
        if not started:
            print("The app has errors and was unable to start it")
            self.stop()
        sys.path.append(self.dest_apps)
        env = {}
        py4web.Session.SECRET = "304c7585-5b74-469f-85ad-e32c5646258d"
        exec("import tagged_posts.models as app_as_module", env)
        self.app_as_module = env.get("app_as_module")
        assert self.app_as_module
        if expect_db:
            assert self.app_as_module and hasattr(
                self.app_as_module, "db"
            ), "no db defined models.py"
        self.base_url = url
        return url

    def stop_py4web(self):
        """Stops the py4web server"""
        if getattr(self, "server", None):
            self.server.kill()
            self.server = None
            shutil.rmtree(self.dest_apps)

    def __del__(self):
        self.stop_py4web()

    def fetch(self, method, url, body={}, cookies=None):
        """Uses mechanize to fetch a page"""
        print(f"Trying {method} {body or ''} to {url} ...")
        if method == "GET":
            response = requests.get(url, allow_redirects=True, cookies=cookies)
        if method == "PUT":
            response = requests.put(url, json=body, cookies=cookies)
        if method == "POST":
            response = requests.post(url, json=body, cookies=cookies)
        if method == "DELETE":
            response = requests.delete(url, cookies=cookies)
        assert (
            response.status_code == 200
        ), f"Expected 200 OK but received {response.status_code}"
        try:
            json = response.json()
        except Exception:
            json = None
        if json is None:
            assert (
                False
            ), f"received:\n{repr(response.content[:80].decode()+'...')}\nand this is invalid JSON"
        print(f"JSON response {json}")
        return json

    def open(self, url):
        """Uses selenium to open a page"""
        self.browser.get(url)
        self.browser.implicitly_wait(10)
        time.sleep(4)

    def create_user(self, user={}):
        """Assume py4web login and register"""
        assert (
            self.app_as_module and "auth_user" in self.app_as_module.db.tables
        ), "cannot find auth_user table"
        db = self.app_as_module.db
        db.auth_user.password.writable = True
        res = db.auth_user.validate_and_insert(**user)
        db.commit()
        assert res.get("id") == 1, "unable to create user"

    def auth_sign_in(self, user={}):
        """Assume py4web login and sign in"""
        self.open(self.base_url + "auth/login")
        email = self.find_first("[name='email']")
        password = self.find_first("[name='password']")
        submit = self.find_first("[type='submit']")
        assert (
            email and password and submit
        ), "expected a login page, but did not find it"
        email.send_keys(user["username"])
        password.send_keys(user["password"])
        submit.click()

    def auth_logout(self):
        """Assume p[y4web login and logout"""
        pass

    def find_all(self, selector):
        """
        Uses selenium to find the selector in the page
        proxy for selenium's find_elements(By.CSS_SELECTOR, selector)
        """
        print(f'Looking for "{selector}" in page')
        return self.browser.find_elements(By.CSS_SELECTOR, selector)

    def find_first(self, selector):
        """Uses selenium to find the selection in the page (first only)"""
        elements = self.find_all(selector)
        assert elements, f"element not found"
        return elements[0]

    def notify(self, message, score=0):
        """Generates a message notification and adds to the score"""
        self.write(f"{message}")
        if score:
            self.write(f"  (points +{score})")
        self._notifications.append((message, score))
        self._score += score

    def stop(self):
        """Stops testing"""
        raise StopTester

    def write(self, msg):
        msg += "\n"
        self._stdout.write(msg)
        self._output += msg

    def run_steps(self, obj):
        """Runs all the testing steps sequentially"""
        self._score = 0
        self._failed = False
        self._stopped = False
        self._output = ""
        self._stdout = sys.stdout
        steps = [name for name in dir(obj) if name.startswith("step_")]
        steps.sort(key=lambda name: int(name[5:]))
        for step in steps:
            self.write("\n" + "=" * 80)
            func = getattr(obj, step)
            self.write(f"{step.title()}: {func.__doc__}")
            self.write("-" * 80)
            sys.stdout = io.StringIO()
            try:
                func()
            except StopTester:
                self._failed = True
                self._stopped = True
            except AssertionError as err:
                print("AssertionError:", err)
            except Exception:
                self._failed = True
                print(traceback.format_exc())
            finally:
                if self._failed:
                    self.write(sys.stdout.getvalue())
                    self.write(f"FAILED")
                    if self._stopped:
                        self.write("Stopping... cannot proceed")
                else:
                    self.write(f"PASS")
            sys.stdout = self._stdout
        self.write("\n" + "=" * 80)
        self.write(f"TOTAL SCORE = {self._score}")
        self.write("=" * 80)
        print(self._output)
        if self.post_grade:
            subprocess.run(
                [
                    "python",
                    "-m",
                    "canvas.cli.assignment.upload-score",
                    self.post_grade["code"],
                    self.post_grade["email"],
                    str(self._score),
                    self._output,
                ],
                shell=False,
                check=True,
            )
        if self._failed:
            sys.exit(1)


############################################################################
# Dogfooding logic
############################################################################


def dockerize(path, args=[]):
    root, test_code = find_repo_root(path)
    print(f"Mounting {root} in a docker container and running {test_code}")
    with tempfile.TemporaryDirectory() as dir:
        dockerfile = os.path.join(dir, "Dockerfile")
        with open(dockerfile, "w") as stream:
            stream.write(DOCKERFILE)
        os.chdir(dir)

        # check if we have podman or docker
        for cmd in ("podman", "docker"):
            try:
                subprocess.run(["which", cmd], check=True)
                break
            except:
                pass
        else:
            raise NotImplementedError

        # build the image
        subprocess.run(
            [cmd, "build", "-t", "selenium", "-f", "Dockerfile", "."],
            check=True,
            shell=False,
        )

        # run provided script within the image
        subprocess.run(
            [
                cmd,
                "run",
                "-it",
                "--rm",
                "--mount",
                f"type=bind,source={root},target=/mounted,readonly",
                "selenium",
                "sh",
                "-c",
                f"python /mounted/{test_code}",
            ],
            check=True,
            shell=False,
        )


if __name__ == "__main__":
    dockerize(sys.argv[1], sys.argv[2:])
