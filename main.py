from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from curl_cffi import requests
from bs4 import BeautifulSoup
import re

app = FastAPI(title="XamToppr Rank Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScoreRequest(BaseModel):
    url: str
    category: str = "UR"
    zone: str = "General"

@app.get("/")
def root():
    return {"status": "online", "engine": "XamToppr DigiALM Universal Scraper"}

@app.post("/api/calculate")
def calculate_score(data: ScoreRequest):
    url = data.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    # Step 1: Chrome Impersonation
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    }
    try:
        res = requests.get(url, impersonate="chrome120", headers=headers, timeout=15)
        if res.status_code != 200:
            raise HTTPException(status_code=400, detail=f"DigiALM HTTP {res.status_code}")
        html_content = res.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraper error: {str(e)}")

    soup = BeautifulSoup(html_content, "html.parser")

    # Step 2: Extract Candidate Details
    cand_name = "Candidate"
    roll_number = "N/A"
    exam_name = "Railway / SSC Online Exam"
    exam_date = "Official Shift"
    exam_time = ""

    for tr in soup.find_all("tr"):
        row_text = tr.get_text()
        cells = tr.find_all("td")
        if len(cells) >= 2:
            k = cells[0].get_text().strip()
            v = cells[1].get_text().strip()
            if "Candidate Name" in k and v: cand_name = v
            elif ("Roll Number" in k or "Participant ID" in k) and v: roll_number = v
            elif ("Subject" in k or "Exam Name" in k) and v: exam_name = v
            elif "Test Date" in k and v: exam_date = v
            elif "Test Time" in k and v: exam_time = v

    # Step 3: Universal DigiALM Question Extraction
    menu_tables = soup.find_all("table", class_=re.compile(r"menu-tbl|menu_tbl", re.I))
    
    questions = []
    correct_cnt = 0
    wrong_cnt = 0
    unatt_cnt = 0
    sections = {}

    for idx, m_tbl in enumerate(menu_tables):
        q_no = idx + 1
        
        # Chosen Option
        chosen_opt = "--"
        tbl_text = m_tbl.get_text()
        m_chosen = re.search(r"Chosen Option\s*:\s*([1-4]|--)", tbl_text, re.I)
        if m_chosen:
            chosen_opt = m_chosen.group(1).strip()

        # Find enclosing question block/parent
        parent = m_tbl.find_parent("table") or m_tbl.find_parent("div")
        if not parent:
            parent = m_tbl

        # Official Key Detection
        correct_opt = "1"
        right_elem = parent.find(class_=re.compile(r"rightAns|correct|bold", re.I))
        if right_elem:
            txt = right_elem.get_text().strip()
            num_m = re.search(r"^([1-4])\.", txt)
            if num_m:
                correct_opt = num_m.group(1)
            else:
                td_right = parent.find("td", class_=re.compile(r"rightAns", re.I))
                if td_right:
                    correct_opt = td_right.get_text().strip()[:1]

        # Status
        if chosen_opt in ["--", "", None]:
            status = "UNATTEMPTED"
            unatt_cnt += 1
        elif str(chosen_opt) == str(correct_opt):
            status = "RIGHT"
            correct_cnt += 1
        else:
            status = "WRONG"
            wrong_cnt += 1

        # Section Grouping
        sec_name = "General Science" if q_no <= 25 else "Mathematics" if q_no <= 55 else "General Intelligence & Reasoning" if q_no <= 85 else "General Awareness"
        if sec_name not in sections:
            sections[sec_name] = {"total": 0, "correct": 0, "wrong": 0, "unattempted": 0}
        sections[sec_name]["total"] += 1
        if status == "RIGHT": sections[sec_name]["correct"] += 1
        elif status == "WRONG": sections[sec_name]["wrong"] += 1
        else: sections[sec_name]["unattempted"] += 1

        # Question Text
        q_text_el = parent.find(class_=re.compile(r"qtext|question-text", re.I))
        q_text = q_text_el.get_text().strip() if q_text_el else f"Official Question Item #{q_no}"

        questions.append({
            "qNo": q_no,
            "section": sec_name,
            "stem": q_text,
            "chosen": chosen_opt,
            "correct": correct_opt,
            "status": status,
            "options": [
                {"id": "1", "text": "Option 1"},
                {"id": "2", "text": "Option 2"},
                {"id": "3", "text": "Option 3"},
                {"id": "4", "text": "Option 4"}
            ]
        })

    # Marks Calculation (+1, -0.33)
    raw_score = round(correct_cnt * 1.0 - wrong_cnt * 0.33, 2)
    display_date = f"{exam_date} ({exam_time})" if exam_time else exam_date

    return {
        "candidate": {
            "name": cand_name,
            "rollNumber": roll_number,
            "examName": exam_name,
            "examDate": display_date,
            "category": data.category,
            "zone": data.zone
        },
        "scores": {
            "totalScore": raw_score,
            "totalCorrect": correct_cnt,
            "totalWrong": wrong_cnt,
            "totalUnattempted": unatt_cnt,
            "totalQuestions": len(questions)
        },
        "sections": sections,
        "questions": questions
    }
