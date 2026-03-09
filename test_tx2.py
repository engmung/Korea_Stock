from youtube_transcript_api import YouTubeTranscriptApi
video_id = 'DOfv6WjVdBE'

try:
    # Just try getting without languages
    tx = YouTubeTranscriptApi.get_transcript(video_id)
    print("Success get_transcript() without args:", len(tx))
except Exception as e:
    print("Failed without args:", e)

try:
    tx_list = YouTubeTranscriptApi.list_transcripts(video_id)
    tx = tx_list.find_transcript(['ko'])
    data = tx.fetch()
    print("Success finding 'ko':", len(data), tx.is_generated)
except Exception as e:
    print("Failed finding 'ko':", e)
