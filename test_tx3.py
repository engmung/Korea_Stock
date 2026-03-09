from youtube_transcript_api import YouTubeTranscriptApi
video_id = 'tBw6s0JjZ9U' # using another recent video id if possible... wait I need one that failed. Let's run a test query to find the actual video_id.

import sqlite3
conn = sqlite3.connect('data/korea_stock.db')
c = conn.cursor()
c.execute("SELECT video_id FROM video_queue WHERE subtitle_status='N' LIMIT 1")
res = c.fetchone()
if res:
    video_id = res[0]
    print("Testing with video:", video_id)
    try:
        tx_list = YouTubeTranscriptApi.list_transcripts(video_id)
        tx = tx_list.find_transcript(['ko'])
        data = tx.fetch()
        print("Success finding 'ko':", len(data), tx.is_generated)
    except Exception as e:
        print("Failed finding 'ko':", e)
