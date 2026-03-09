import os
from dotenv import load_dotenv

load_dotenv()
proxy = os.getenv("YOUTUBE_PROXY_URL")
print("Original proxy string:", proxy)

import requests
import random

if proxy:
    # Test random proxy 1~10
    test_proxy = proxy.replace("{id}", str(random.randint(1, 10)))
    proxies = {
        "http": test_proxy,
        "https": test_proxy
    }
    print("Testing with proxies config:", proxies)
    try:
        res = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=10)
        print("Success! IP returned:", res.json())
    except Exception as e:
        print("Failed to use proxy!", e)

# Test youtube-transcript-api behavior
from youtube_transcript_api import YouTubeTranscriptApi
video_id = 'tBw6s0JjZ9U'
try:
    print("Testing youtube-transcript-api with proxy...")
    tx = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    print("Success youtube-transcript-api!")
except Exception as e:
    print("youtube-transcript-api failed:", type(e).__name__, e)
