import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def parse_formatting(text: str) -> List[Dict[str, Any]]:
    """마크다운 텍스트 내의 강조, 기울임, 코드 등 서식을 Notion 리치 텍스트로 변환합니다."""
    if not text or not text.strip():
        return []
    
    # ** 패턴을 찾아서 처리
    result = []
    parts = re.split(r'(\*\*.*?\*\*)', text)
    
    for part in parts:
        # ** 패턴 처리
        if part.startswith('**') and part.endswith('**'):
            content = part[2:-2]  # ** 제거
            result.append({
                "type": "text",
                "text": {"content": content},
                "annotations": {"bold": True}
            })
        else:
            # 일반 텍스트 처리
            if part:
                result.append({
                    "type": "text",
                    "text": {"content": part}
                })
    
    return result if result else [{"type": "text", "text": {"content": text}}]


def create_markdown_blocks(content: str) -> List[Dict[str, Any]]:
    """마크다운 텍스트를 Notion 블록으로 변환합니다."""
    blocks = []
    lines = content.split('\n')
    i = 0
    current_text = ""
    MAX_TEXT_LENGTH = 1900  # Notion API 제한보다 안전하게 설정
    
    while i < len(lines):
        line = lines[i]
        
        # 제목 처리 (# 시작)
        if line.startswith('# '):
            # 기존 텍스트 처리
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 새 제목 블록
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": line[2:]}}]
                }
            })
            
        # 부제목 처리 (## 시작)
        elif line.startswith('## '):
            # 기존 텍스트 처리
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 새 부제목 블록
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": line[3:]}}]
                }
            })
            
        # 소제목 처리 (### 시작)
        elif line.startswith('### '):
            # 기존 텍스트 처리
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 새 소제목 블록
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": line[4:]}}]
                }
            })
            
        # 구분선 처리 (---)
        elif line.strip() == '---':
            # 기존 텍스트 처리
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 구분선 블록
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })
            
        # 불릿 포인트 처리 (- 또는 * 시작)
        elif (line.strip().startswith('- ') or line.strip().startswith('* ')) and not line.strip().startswith('- [ ]') and not line.strip().startswith('- [x]'):
            # 기존 텍스트 처리
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 불릿 포인트 내용 추출
            if line.strip().startswith('- '):
                content = line.strip()[2:]
            else:  # * 시작
                content = line.strip()[2:]
            
            # 불릿 포인트 블록
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": parse_formatting(content)
                }
            })
            
        # 빈 줄 처리
        elif not line.strip():
            # 이전 텍스트가 있을 경우 블록 추가
            if current_text.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text.strip())
                    }
                })
                current_text = ""
            
            # 빈 줄이 여러 개 연속되면 하나의 빈 단락만 추가
            if i + 1 < len(lines) and lines[i + 1].strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": []
                    }
                })
            
        # 일반 텍스트 행
        else:
            current_text += line + "\n"
            
            # 텍스트가 너무 길어지면 분할
            if len(current_text) > MAX_TEXT_LENGTH:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": parse_formatting(current_text[:MAX_TEXT_LENGTH].strip())
                    }
                })
                current_text = current_text[MAX_TEXT_LENGTH:]
        
        i += 1
    
    # 마지막 남은 텍스트 처리
    if current_text.strip():
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": parse_formatting(current_text.strip())
            }
        })
    
    return blocks

def split_into_blocks(content: str) -> List[Dict[str, Any]]:
    """
    마크다운 텍스트를 Notion API 호출을 위한 블록 리스트로 변환합니다.
    이 함수는 create_markdown_blocks의 래퍼 함수입니다.
    """
    return create_markdown_blocks(content)