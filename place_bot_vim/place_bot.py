from enum import Enum
import time
import json
from io import BytesIO

import requests
from bs4 import BeautifulSoup
import websocket
from PIL import Image
import numpy as np

from . import queries


class Color(Enum):
    RED = 2
    ORANGE = 3
    YELLOW = 4
    DARK_GREEN = 6
    LIGHT_GREEN = 8
    DARK_BLUE = 12
    BLUE = 13
    LIGHT_BLUE = 14
    DARK_PURPLE = 18
    PURPLE = 19
    LIGHT_PINK = 23
    BROWN = 25
    BLACK = 27
    GRAY = 29
    LIGHT_GRAY = 30
    WHITE = 31


class Placer:
    REDDIT_URL = "https://www.reddit.com"
    LOGIN_URL = REDDIT_URL + "/login"
    INITIAL_HEADERS = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": REDDIT_URL,
        "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36"
    }

    def __init__(self):
        self.client = requests.session()
        self.client.headers.update(self.INITIAL_HEADERS)

        self.token = None

    def login(self, username: str, password: str):
        # get the csrf token
        r = self.client.get(self.LOGIN_URL)
        login_get_soup = BeautifulSoup(r.content, "html.parser")
        csrf_token = login_get_soup.find("input", {"name": "csrf_token"})["value"]
        time.sleep(1)

        # authenticate
        r = self.client.post(
            self.LOGIN_URL,
            data={
                "username": username,
                "password": password,
                "dest": self.REDDIT_URL,
                "csrf_token": csrf_token
            }
        )
        time.sleep(1)

        assert r.status_code == 200, "error logging in"

        # get the new access token
        r = self.client.get(self.REDDIT_URL)
        data_str = BeautifulSoup(r.content, "html.parser").find("script", {"id": "data"}).contents[0][len("window.__r = "):-1]
        data = json.loads(data_str)
        self.token = data["user"]["session"]["accessToken"]

    def place_tile(self, x: int, y: int, color: Color):
        # handle 2nd canvas
        canvas_index = x // 1000
        x -= canvas_index * 1000

        headers = self.INITIAL_HEADERS.copy()
        headers.update({
            "apollographql-client-name": "mona-lisa",
            "apollographql-client-version": "0.0.1",
            "content-type": "application/json",
            "origin": "https://hot-potato.reddit.com",
            "referer": "https://hot-potato.reddit.com/",
            "sec-fetch-site": "same-site",
            "authorization": "Bearer " + self.token
        })

        r = requests.post(
            "https://gql-realtime-2.reddit.com/query",
            json={
                "operationName": "setPixel",
                "query": queries.SET_PIXEL_QUERY,
                "variables": {
                    "input": {
                        "PixelMessageData": {
                            "canvasIndex": canvas_index,
                            "colorIndex": color.value,
                            "coordinate": {
                                "x": x,
                                "y": y
                            }
                        },
                        "actionName": "r/replace:set_pixel"
                    }
                }
            },
            headers=headers
        )

        assert r.status_code == 200, "error setting pixel"

    def get_map_data(self):
        r = requests.get(self._get_map_url())
        assert r.status_code == 200, "error getting map data"

        im = Image.open(BytesIO(r.content))
        map_data = np.array(im.getdata())
        map_data = np.reshape(map_data, (1000, 1000))

        # all color values are off by 1
        map_data = map_data - 1

        return map_data

    def _get_map_url(self):
        ws = websocket.create_connection("wss://gql-realtime-2.reddit.com/query")
        ws.send(json.dumps({
            "type": "connection_init",
            "payload": {
                "Authorization": "Bearer " + self.token
            }
        }))
        ws.send(json.dumps({
            "type": "start",
            "id": "1",
            "payload": {
                "extensions": {},
                "operationName": "replace",
                "query": queries.FULL_FRAME_MESSAGE_SUBSCRIBE_QUERY,
                "variables": {
                    "input": {
                        "channel": {
                            "category": "CANVAS",
                            "tag": "0",
                            "teamOwner": "AFD2022"
                        }
                    }
                }
            }
        }))

        while True:
            result = json.loads(ws.recv())
            if "id" not in result:
                continue
            if result["id"] != "1":
                continue
            assert result["payload"]["data"]["subscribe"]["data"]["__typename"] == "FullFrameMessageData"
            return result["payload"]["data"]["subscribe"]["data"]["name"]
