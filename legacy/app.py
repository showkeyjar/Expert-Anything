from __future__ import annotations

import base64
import html
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
ASSETS = DATA / "assets"
STATE_FILE = DATA / "learner.json"
PORT = int(os.environ.get("EXPERTANYTHING_PORT", "8000"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.setdefault("mastery", {})
        state.setdefault("history", [])
        state.setdefault("weaknesses", [])
        return state
    return {"mastery": {}, "history": [], "weaknesses": [], "profile": {}}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        chunks = []
        with zipfile.ZipFile(path) as book:
            for name in book.namelist():
                if name.lower().endswith((".xhtml", ".html", ".htm")):
                    chunks.append(clean_text(book.read(name).decode("utf-8", errors="ignore")))
        return "\n\n".join(chunks)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = [(page.extract_text() or "") for page in reader.pages]
            text = "\n\n".join(pages)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except Exception:
            return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        generic = ("目录" in line and ("内容简介" in line or "第一章" in line)) or re.fullmatch(r"[·.\s\d-]+", line or "")
        if line and not generic and len(line) <= 100:
            return line[:100]
    return Path(fallback).stem.replace("_", " ").replace("-", " ").title()


def generic_title(title: str) -> bool:
    return bool(title and (("目录" in title and "内容简介" in title) or re.fullmatch(r"[·.\s\d-]+", title)))


def normalize_heading(line: str) -> str:
    line = re.sub(r"\.{3,}.*$", "", line).strip()
    line = re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", line)
    line = re.sub(r"^\s*第\s*\d+\s*章\s*", "", line)
    return line.strip(" .·-\t")


def build_knowledge(text: str, filename: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    markdown_headings = [re.sub(r"^#+\s*", "", line).strip() for line in lines if line.startswith("#")]
    document_headings = [normalize_heading(line) for line in lines if re.search(r"第\s*\d+\s*章|^\d+(?:\.\d+)+\s+", line)]
    headings = [heading for heading in markdown_headings + document_headings if heading and len(heading) <= 120 and not generic_title(heading)]
    has_structure = bool(headings)
    paragraphs = [line for line in lines if not line.startswith("#")]
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|\n+", text) if part.strip()]
    if not headings:
        headings = ["核心概念", "实践与反馈"]
    stopwords = {"this", "that", "with", "from", "self", "return", "class", "def", "true", "false", "系统", "用户", "知识", "目录", "章节", "内容", "说明", "示例", "参考", "前言", "摘要", "结语", "问题", "方法", "过程", "结果", "部分", "第一章", "第二章", "第三章", "第四章", "第五章", "帮助", "介绍", "需要", "可以", "通过", "进行", "支持", "实现", "影响", "相关", "当前", "一个", "一种", "什么", "如何", "我们", "你们", "他们", "学习者"}
    candidate_scores = {}
    for heading in (headings if has_structure else []):
        if 2 <= len(heading) <= 24 and heading not in stopwords:
            candidate_scores[heading] = candidate_scores.get(heading, 0) + 5
    if has_structure:
        for sentence in sentences:
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", sentence):
                if word.lower() not in stopwords:
                    candidate_scores[word] = candidate_scores.get(word, 0) + 1
    keywords = []
    for word, score in sorted(candidate_scores.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
        occurrences = sum(1 for sentence in sentences if word.lower() in sentence.lower())
        is_heading = word in headings and has_structure
        if (is_heading or occurrences >= 2) and not any(word != existing and word in existing for existing in keywords):
            keywords.append(word)
        if len(keywords) >= 8:
            break
    concepts = []
    for i, word in enumerate(keywords[:8]):
        evidence = [sentence[:360] for sentence in sentences if word.lower() in sentence.lower()][:3]
        concepts.append({"id": f"c{i}", "name": word, "summary": evidence[0] if evidence else "未找到对应原文片段。", "evidence": evidence, "mastery": 0.0})
    if not concepts:
        concepts = [{"id": "c0", "name": "原文结构", "summary": "未能从文本中识别出稳定的概念词，请先阅读原文。", "evidence": [], "mastery": 0.0}]
    relations = []
    seen_relations = set()
    for sentence in sentences:
        matched = [concept for concept in concepts if concept["name"].lower() in sentence.lower()]
        for left_index, left in enumerate(matched):
            for right in matched[left_index + 1:]:
                key = (left["id"], right["id"])
                if key not in seen_relations:
                    relations.append({"from": left["id"], "to": right["id"], "type": "co_occurs", "evidence": sentence[:360]})
                    seen_relations.add(key)
    exercises = [{"id": f"q{i}", "concept_id": concept["id"], "prompt": f"根据原文，用自己的话解释“{concept['name']}”，并指出原文中支持你回答的关键句。", "answer_hint": concept["summary"]} for i, concept in enumerate(concepts[:5])]
    return {"asset_id": str(uuid.uuid4()), "type": Path(filename).suffix.lower().lstrip(".") or "text", "title": title_from(text, filename), "source_name": filename, "created_at": now(), "analysis": {"status": "source_grounded", "method": "deterministic_extraction_v6", "notice": "当前 MVP 只做基于原文的结构化提取，不把关键词提取当作完整理解。"}, "source_text": text, "chapters": [{"id": f"ch{i}", "title": heading, "order": i + 1} for i, heading in enumerate(headings[:8])], "concepts": concepts, "relations": relations, "learning_path": [concept["id"] for concept in concepts], "exercises": exercises, "source_excerpt": " ".join(paragraphs)[:1600]}


def load_assets() -> list[dict]:
    result = []
    for file in sorted(ASSETS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        asset = json.loads(file.read_text(encoding="utf-8"))
        if asset.get("source_text") and asset.get("analysis", {}).get("method") != "deterministic_extraction_v6":
            rebuilt = build_knowledge(asset["source_text"], asset.get("source_name", file.stem))
            rebuilt["asset_id"] = asset.get("asset_id", rebuilt["asset_id"])
            rebuilt["created_at"] = asset.get("created_at", rebuilt["created_at"])
            asset = rebuilt
            write_json(file, asset)
        if generic_title(asset.get("title", "")):
            asset["title"] = Path(asset.get("source_name", file.stem)).stem.replace("_", " ").replace("-", " ").title()
        result.append(asset)
    return result


def save_asset(asset: dict) -> None:
    write_json(ASSETS / f"{asset['asset_id']}.json", asset)


def public_asset(asset: dict) -> dict:
    result = {key: value for key, value in asset.items() if key != "source_text"}
    result["source_length"] = len(asset.get("source_text", ""))
    return result


def source_pages(text: str, page_size: int = 2800) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    pages = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > page_size:
            pages.append(current)
            current = ""
        if len(paragraph) > page_size:
            if current:
                pages.append(current)
                current = ""
            pages.extend(paragraph[i:i + page_size] for i in range(0, len(paragraph), page_size))
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        pages.append(current)
    return pages or [""]


def tutor_session(asset: dict, learner: dict) -> dict:
    profile = learner.get("profile", {})
    if not profile.get("goal"):
        return {"phase": "align", "agent": "Tutor Agent", "title": f"开始学习《{asset['title']}》", "message": "我已经加载了这份知识资产，并建立了可追溯的知识索引。开始教之前，我先了解你的目标和已有认知。", "asset_title": asset["title"], "concept_count": len(asset.get("concepts", []))}
    concepts = asset.get("concepts", [])
    selected = min(concepts, key=lambda item: learner.get("mastery", {}).get(item["id"], 0)) if concepts else None
    if not selected:
        return {"phase": "complete", "agent": "Tutor Agent", "title": "当前资产学习完成", "message": "已经完成这份知识资产的学习记录。", "asset_title": asset["title"]}
    evidence = selected.get("evidence", [])
    return {"phase": "teach", "agent": "Tutor Agent", "title": f"我们先建立：{selected['name']}", "message": f"先形成一个能工作的心智模型，再用一个最小反馈动作确认它是否真的对你有用。", "concept": selected, "source_evidence": evidence, "knowledge_path": [{"name": item["name"], "mastery": learner.get("mastery", {}).get(item["id"], 0)} for item in concepts[:6]], "example": f"把“{selected['name']}”放到你的目标“{profile.get('goal', '当前学习目标')}”里，可以先观察：它解决的具体问题是什么？它会改变哪一步行动？", "visual_steps": [asset["title"], selected["name"], "你的目标", "下一步行动"], "prompt": f"如果你现在要把“{selected['name']}”用到“{profile.get('goal', '你的目标')}”中，你认为第一步应该改变什么？用一两句话回答即可。", "feedback": learner.get("last_feedback")}


def respond(handler: BaseHTTPRequestHandler, payload: dict, status=HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/state":
            assets = load_assets()
            state = read_state()
            if assets:
                return respond(self, {"asset": public_asset(assets[0]), "assets": [public_asset(asset) for asset in assets], "learner": state, "session": tutor_session(assets[0], state)})
            return respond(self, {"asset": None, "assets": [], "learner": state, "session": None})
        if route.startswith("/api/assets/") and route.endswith("/source"):
            asset_id = route.split("/")[3]
            asset = next((item for item in load_assets() if item["asset_id"] == asset_id), None)
            if not asset:
                return respond(self, {"error": "asset not found"}, HTTPStatus.NOT_FOUND)
            query = parse_qs(urlparse(self.path).query)
            page = max(0, int(query.get("page", [0])[0]))
            pages = source_pages(asset.get("source_text", ""))
            page = min(page, len(pages) - 1)
            return respond(self, {"asset_id": asset_id, "title": asset["title"], "page": page, "total_pages": len(pages), "text": pages[page], "has_previous": page > 0, "has_next": page < len(pages) - 1})
        if route.startswith("/api/assets/"):
            asset_id = route.rsplit("/", 1)[-1]
            asset = next((item for item in load_assets() if item["asset_id"] == asset_id), None)
            return respond(self, {"asset": public_asset(asset)} if asset else {"error": "asset not found"}, HTTPStatus.OK if asset else HTTPStatus.NOT_FOUND)
        target = STATIC / ("index.html" if route == "/" else route.lstrip("/"))
        if target.exists() and target.is_file():
            content = target.read_bytes()
            types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{types.get(target.suffix, 'application/octet-stream')}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if route == "/api/assets":
            payload = json.loads(raw or b"{}")
            filename = payload.get("filename", "learning-note.md")
            temp_path = None
            if payload.get("content_base64"):
                file_descriptor, temp_name = tempfile.mkstemp(suffix=Path(filename).suffix)
                os.close(file_descriptor)
                temp_path = Path(temp_name)
                temp_path.write_bytes(base64.b64decode(payload["content_base64"]))
                text = extract_source(temp_path)
                temp_path.unlink(missing_ok=True)
            else:
                text = payload.get("text", "")
            if not text.strip():
                return respond(self, {"error": "请提供材料内容"}, HTTPStatus.BAD_REQUEST)
            asset = build_knowledge(text, filename)
            save_asset(asset)
            return respond(self, {"asset": public_asset(asset)}, HTTPStatus.CREATED)
        if route == "/api/session/align":
            payload = json.loads(raw or b"{}")
            state = read_state()
            state["profile"] = {"goal": payload.get("goal", "理解这份知识资产"), "baseline": payload.get("baseline", "不确定"), "style": payload.get("style", "先看例子")}
            state["current_asset"] = payload.get("asset_id")
            write_json(STATE_FILE, state)
            asset = next((item for item in load_assets() if item["asset_id"] == payload.get("asset_id")), None)
            if not asset:
                return respond(self, {"error": "asset not found"}, HTTPStatus.NOT_FOUND)
            return respond(self, {"learner": state, "session": tutor_session(asset, state)})
        if route == "/api/session/respond":
            payload = json.loads(raw or b"{}")
            state = read_state()
            concept_id = payload.get("concept_id")
            confidence = max(0, min(1, float(payload.get("confidence", 0.5))))
            previous = state["mastery"].get(concept_id, 0.0)
            mastery = round(previous * 0.65 + confidence * 0.35, 2)
            state["mastery"][concept_id] = mastery
            state["history"].insert(0, {"concept_id": concept_id, "score": confidence, "answer": payload.get("answer", ""), "at": now()})
            state["history"] = state["history"][:20]
            state["weaknesses"] = [key for key, value in state["mastery"].items() if value < 0.6]
            state["last_feedback"] = {"concept_id": concept_id, "mastery": mastery, "message": "回答已记录。当前 MVP 先使用你的把握度作为学习信号，语义评估将在 Tutor 接入模型后完成。", "at": now()}
            write_json(STATE_FILE, state)
            asset = next((item for item in load_assets() if item["asset_id"] == payload.get("asset_id")), None)
            if not asset:
                return respond(self, {"error": "asset not found"}, HTTPStatus.NOT_FOUND)
            return respond(self, {"learner": state, "session": tutor_session(asset, state), "mastery": mastery})
        if route == "/api/explain":
            payload = json.loads(raw or b"{}")
            asset = next((item for item in load_assets() if item["asset_id"] == payload.get("asset_id")), None)
            concept = next((item for item in (asset or {}).get("concepts", []) if item["id"] == payload.get("concept_id")), None)
            if not concept:
                return respond(self, {"error": "concept not found"}, HTTPStatus.NOT_FOUND)
            depth = max(1, min(3, int(payload.get("depth", 1))))
            evidence = concept.get("evidence", [])
            if not evidence:
                return respond(self, {"error": "没有找到这个概念对应的原文证据，暂时不能生成解释。"}, HTTPStatus.UNPROCESSABLE_ENTITY)
            labels = {1: "原文定位", 2: "证据整理", 3: "学习提示"}
            next_steps = {1: "继续查看证据整理，或进入练习检验你是否读懂。", 2: "继续查看学习提示，或用自己的话回答练习。", 3: "现在进入练习，把原文中的说法迁移到你的问题。"}
            return respond(self, {"explanation": {"title": concept["name"], "depth": depth, "label": labels[depth], "definition": evidence[min(depth - 1, len(evidence) - 1)], "why": "这段内容直接来自上传资产的原文。当前 MVP 不添加原文没有提供的事实；更高层内容只是阅读提示，不是新的知识结论。", "next": next_steps[depth], "evidence": evidence}})
        if route == "/api/attempts":
            payload = json.loads(raw or b"{}")
            state = read_state()
            concept_id = payload.get("concept_id")
            score = max(0, min(1, float(payload.get("score", 0))))
            previous = state["mastery"].get(concept_id, 0.0)
            mastery = round(previous * 0.65 + score * 0.35, 2)
            state["mastery"][concept_id] = mastery
            state["history"].insert(0, {"concept_id": concept_id, "score": score, "at": now()})
            state["history"] = state["history"][:20]
            state["weaknesses"] = [key for key, value in state["mastery"].items() if value < 0.6]
            write_json(STATE_FILE, state)
            return respond(self, {"learner": state, "mastery": mastery})
        respond(self, {"error": "route not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        route = urlparse(self.path).path
        if route.startswith("/api/assets/"):
            asset_id = route.rsplit("/", 1)[-1]
            asset = next((item for item in load_assets() if item["asset_id"] == asset_id), None)
            if not asset:
                return respond(self, {"error": "asset not found"}, HTTPStatus.NOT_FOUND)
            (ASSETS / f"{asset['asset_id']}.json").unlink(missing_ok=True)
            return respond(self, {"deleted": asset_id})
        respond(self, {"error": "route not found"}, HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), AppHandler)
    print(f"ExpertAnything MVP running at http://127.0.0.1:{PORT}")
    server.serve_forever()
