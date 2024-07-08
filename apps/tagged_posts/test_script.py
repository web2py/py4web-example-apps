import os
import sys
import time

THIS_FOLDER = os.path.dirname(__file__)
sys.path.append(os.path.join(THIS_FOLDER, "../../tools/"))
from tester import Tester


class TestTaggedPosts:
    def __init__(self):
        self.tester = Tester(headless=True)
        self.url = self.tester.start_py4web(THIS_FOLDER, port=8888)
        self.cookies = None

    def run(self):
        self.tester.run_steps(self)

    def step_01(self):
        "check we can open the page"
        self.tester.open(self.url)
        self.tester.notify("Success in opening page")

    def step_02(self):
        "check login"
        user = dict(
            username="tester",
            email="tester@example.com",
            password="1234qwerQWER!@#$",
            first_name="Tester",
            last_name="TESTER",
        )
        self.tester.create_user(user)
        self.tester.auth_sign_in(user)
        self.tester.open(self.url)
        assert "tester" in self.tester.browser.page_source, "unable to login"
        assert "logout" in self.tester.browser.page_source, "unable to login"
        set_cookies = self.tester.browser.get_cookies()
        assert len(set_cookies) >= 1, "server cookies not working"
        self.cookies = {"tagged_posts_session": set_cookies[0]["value"]}
        db = self.tester.app_as_module.db
        assert "post_item" in db.tables, "table post_item not found in models.py"
        post_item = db.post_item
        assert "content" in post_item.fields, "post_item has no content field"
        assert "created_on" in post_item.fields, "post_item has no created_on field"
        assert "created_by" in post_item.fields, "post_item has no created_by field"
        assert (
            post_item.created_on.type == "datetime"
        ), "post_item.created_on must be a datetime"
        assert (
            post_item.created_by.type == "reference auth_user"
        ), "post_item.created_by must be a reference"
        self.tester.notify("Table post_item defined correctly", score=1.0)

        assert "tag_item" in db.tables, "table tag_item not found in models.py"
        tag_item = db.tag_item
        assert "name" in tag_item.fields, "tag_item has no name field"
        assert "post_item_id" in tag_item.fields, "tag_item has no post_item_id field"
        assert (
            tag_item.post_item_id.type == "reference post_item"
        ), "tag_item.post_item_id must be a reference"
        self.tester.notify("Table tag_item defined correctly", score=1.0)

    def step_03(self):
        "check api"
        if not self.cookies:
            self.tester.notify("Cannot proceed if unable to login")
            self.tester.stop()
        # self.url = "http://127.0.0.1:8000/bird_spotter/"
        try:
            content = "This is a message about #fun #games"
            res = self.tester.fetch(
                "POST",
                self.url + "api/posts",
                {"content": content},
            )
            assert res.get("id") == 1, "unable to store a post_item using API"
        except:
            pass
        else:
            assert False, "I should not have been able to access API without Login"

        content = "This is a message about #fun #games"
        res = self.tester.fetch(
            "POST",
            self.url + "api/posts",
            {"content": content},
            cookies=self.cookies,
        )
        assert res.get("id") == 1, "unable to store a post_item using API"

        time.sleep(1)

        content = "This is a message about #boring #games"
        res = self.tester.fetch(
            "POST",
            self.url + "api/posts",
            {"content": content},
            cookies=self.cookies,
        )
        assert res.get("id") == 2, "unable to store a post_item using API"
        self.tester.notify("POST to /api/posts works", score=1.0)

        res = self.tester.fetch("GET", self.url + "api/tags", cookies=self.cookies)
        assert res == {
            "tags": ["boring", "fun", "games"]
        }, "Did not receive correct tags"
        self.tester.notify("GET to /api/tags works", score=1.0)

        res = self.tester.fetch("GET", self.url + "api/posts", cookies=self.cookies)
        assert "posts" in res, 'expected {"posts": [...]}'
        assert len(res["posts"]) == 2, "expected to posts in response"
        assert (
            "#boring" in res["posts"][0]["content"]
        ), "expected the first post to containt #boring"
        assert (
            "#fun" in res["posts"][1]["content"]
        ), "expected the second post to containt #boring"
        self.tester.notify("GET to /api/posts works", score=0.4)

        res = self.tester.fetch(
            "GET", self.url + "api/posts?tags=fun", cookies=self.cookies
        )
        assert "posts" in res, 'expected {"posts": [...]}'
        assert len(res["posts"]) == 1, "expected to posts in response"
        assert (
            "#fun" in res["posts"][0]["content"]
        ), "expected the second post to containt #boring"
        self.tester.notify("GET to /api/posts?tags=fun works", score=0.3)

        res = self.tester.fetch(
            "GET", self.url + "api/posts?tags=fun,boring", cookies=self.cookies
        )
        assert "posts" in res, 'expected {"posts": [...]}'
        assert len(res["posts"]) == 2, "expected to posts in response"
        self.tester.notify("GET to /api/posts?tags=fun,boring works", score=0.3)

        res = self.tester.fetch(
            "DELETE", self.url + "api/posts/1", cookies=self.cookies
        )
        db = self.tester.app_as_module.db
        assert db(db.post_item).count() == 1, "unable to delete post"
        self.tester.notify("DELETE to /api/posts works", score=1.0)

    def step_04(self):
        """check post items"""
        self.tester.open(self.url)
        self.tester.find_first("textarea.post-content")
        self.tester.find_first("button.submit-content")
        self.tester.find_first(".feed")
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 1, "Expected to find one post_item"
        assert "#boring" in items[0].get_attribute(
            "innerHTML"
        ), "Exepcted to find a post_item"
        self.tester.notify("Feed column works", score=1.0)

    def step_05(self):
        """check tags"""
        self.tester.find_first(".tags")
        tags = self.tester.find_all(".tags .tag")
        assert len(tags) == 2, "did not find the expected tags"
        assert "boring" in tags[0].text, "Exepcted the boring tag"
        assert "games" in tags[1].text, "Exepcted the games tag"
        self.tester.notify("Tags column works", score=1.0)

    def step_06(self):
        """check filter by tags"""
        self.tester.open(self.url)
        content = "#hello #world"
        self.tester.find_first("textarea.post-content").send_keys(content)
        self.tester.find_first("button.submit-content").click()
        time.sleep(1)

        db = self.tester.app_as_module.db
        assert db(db.post_item).count() == 2, "record not inserted in database"
        self.tester.notify("Posting from page works", score=0.5)

        self.tester.find_first(".feed")
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 2, "Exepcted to find two post_items"
        assert "#hello" in items[0].get_attribute(
            "innerHTML"
        ), "Exepcted to find a post_item"
        assert "#world" in items[0].get_attribute(
            "innerHTML"
        ), "Exepcted to find a post_item"
        self.tester.notify("Posting to the feed works", score=0.5)

        tags = self.tester.find_all(".tags .tag")
        assert "boring" in tags[0].text, "Exepcted the boring tag"
        assert "games" in tags[1].text, "Exepcted the games tag"
        assert "hello" in tags[2].text, "Exepcted the hello tag"
        assert "world" in tags[3].text, "Exepcted the world tag"
        self.tester.notify("Tags refreshed correclty", score=1.0)

        tags[0].click()
        time.sleep(1)
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 1, "Exepcted to find one post_item"
        assert "#boring" in items[0].get_attribute(
            "innerHTML"
        ), "Exepcted to find a post_item"
        assert "#games" in items[0].get_attribute(
            "innerHTML"
        ), "Exepcted to find a post_item"
        self.tester.notify("Tags toggling works", score=0.5)

        tags[0].click()
        time.sleep(1)
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 2, "Exepcted to find two post_item"
        self.tester.notify("Tags untoggling works", score=0.5)

    def step_07(self):
        """check delete item"""
        self.tester.open(self.url)
        items = self.tester.find_all(".feed .post_item")
        buttons = self.tester.find_all(".feed .post_item button")
        assert len(items) == 2, "Expected two post_items"
        assert len(buttons) == 2, "Expected a delete button per item"
        buttons[0].click()
        time.sleep(1)
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 1, "Expected the item to be deleted"
        self.tester.open(self.url)
        items = self.tester.find_all(".feed .post_item")
        assert len(items) == 1, "Expected the item to be deleted"
        self.tester.notify("Delete using the feed button works", score=1.0)


if __name__ == "__main__":
    TestTaggedPosts().run()
