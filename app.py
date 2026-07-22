
from pathlib import Path
from datetime import datetime
import json
import re
import subprocess
import sys
import uuid

import gradio as gr
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

HYBRID_PATH = SRC_DIR / "hybrid_audit_mode.py"
AGENT_PATH = SRC_DIR / "generic_runtime_agent.py"
DART_PIPELINE_PATH = SRC_DIR / "hybe_dart_pipeline.py"

VERIFIED_ROOT = PROJECT_ROOT / "verified_demo"
RUN_ROOT = PROJECT_ROOT / "web_runs"
SAMPLES_DIR = PROJECT_ROOT / "samples"

CURRENT_TEMPLATE = (
    SAMPLES_DIR
    / "current_year_unaudited_template.csv"
)

DISCLAIMER = (
    "식별된 Red Flag는 오류나 부정의 존재를 의미하는 것이 아니라, "
    "기업 및 환경에 대한 이해와 중요왜곡표시위험 평가를 위해 "
    "추가적인 질문과 검토가 필요한 영역을 의미한다."
)

REQUIRED_ACCOUNTS = [
    "Revenue",
    "Operating_Profit",
    "Net_Income",
    "Total_Assets",
    "Operating_Cash_Flow",
    "Intangible_Assets",
    "Goodwill",
    "Investment_in_Associates",
    "Accounts_Receivable",
    "Inventory",
    "Trade_Payables",
]

VERIFIED_COMPANIES = {
    "삼성전자": "samsung_electronics",
    "NAVER": "naver",
    "카카오": "kakao",
    "하이브": "hybe",
}


# =========================================================
# 공통 유틸리티
# =========================================================
def make_run_dir(mode):
    run_id = (
        datetime.now().strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )

    run_dir = RUN_ROOT / mode / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    return run_dir


def file_path(value):
    if value is None:
        return None

    if isinstance(value, str):
        return Path(value)

    if hasattr(value, "name"):
        return Path(value.name)

    return Path(str(value))


def read_csv_flexible(path):
    path = Path(path)

    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        return pd.read_csv(
            path,
            encoding="utf-8-sig",
        )


def validate_standard_csv(
    csv_path,
    expected_year_count=None,
):
    df = read_csv_flexible(csv_path)

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    if "Account" not in df.columns:
        raise ValueError("Account 컬럼이 없습니다.")

    df["Account"] = (
        df["Account"]
        .astype(str)
        .str.strip()
    )

    if len(df) != 11:
        raise ValueError(
            f"계정 행은 11개여야 합니다. 현재 {len(df)}개입니다."
        )

    if df["Account"].duplicated().any():
        duplicates = (
            df.loc[
                df["Account"].duplicated(),
                "Account",
            ]
            .tolist()
        )

        raise ValueError(
            "중복 계정이 있습니다: "
            + ", ".join(duplicates)
        )

    missing = sorted(
        set(REQUIRED_ACCOUNTS)
        - set(df["Account"])
    )

    unexpected = sorted(
        set(df["Account"])
        - set(REQUIRED_ACCOUNTS)
    )

    if missing:
        raise ValueError(
            "누락 계정: " + ", ".join(missing)
        )

    if unexpected:
        raise ValueError(
            "허용되지 않은 계정: "
            + ", ".join(unexpected)
        )

    year_columns = [
        str(column)
        for column in df.columns
        if re.fullmatch(r"\d{4}", str(column))
    ]

    if expected_year_count is not None:
        if len(year_columns) != expected_year_count:
            raise ValueError(
                f"연도 컬럼은 {expected_year_count}개여야 합니다. "
                f"현재: {year_columns}"
            )

    for column in year_columns:
        converted = pd.to_numeric(
            df[column],
            errors="coerce",
        )

        if converted.isna().any():
            invalid_accounts = (
                df.loc[
                    converted.isna(),
                    "Account",
                ]
                .tolist()
            )

            raise ValueError(
                f"{column} 컬럼에 숫자가 아닌 값이 있습니다: "
                + ", ".join(invalid_accounts)
            )

        df[column] = converted

    return df, year_columns


def find_latest_file(directory, pattern):
    directory = Path(directory)

    if not directory.exists():
        return None

    files = sorted(
        directory.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    return files[0] if files else None


def extract_path_from_stdout(stdout, label):
    pattern = rf"{re.escape(label)}\s*:\s*(.+)"

    matches = re.findall(
        pattern,
        stdout or "",
    )

    if not matches:
        return None

    return Path(matches[-1].strip())


def read_json_and_report(
    json_path,
    markdown_path,
):
    with Path(json_path).open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    report = Path(markdown_path).read_text(
        encoding="utf-8",
    )

    return data, report


def recursive_find_lists(data, key_words):
    results = []

    normalized_words = [
        re.sub(r"[^a-z0-9가-힣]", "", word.lower())
        for word in key_words
    ]

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = re.sub(
                    r"[^a-z0-9가-힣]",
                    "",
                    str(key).lower(),
                )

                if any(
                    word in normalized_key
                    for word in normalized_words
                ):
                    if isinstance(child, list):
                        results.append(child)

                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)

    return results[0] if results else []



def normalize_signal_text(value):
    return re.sub(
        r"[^a-z0-9가-힣]",
        "",
        str(value or "").lower(),
    )


def classify_signal_item(item):
    """
    규칙 결과 딕셔너리 한 건이 Red Flag인지
    Monitoring Signal인지 판단한다.
    """
    if not isinstance(item, dict):
        return None

    classification_keys = [
        "status",
        "classification",
        "signal_type",
        "signal_level",
        "result_type",
        "level",
        "severity",
        "판정",
        "구분",
    ]

    candidate_values = []

    for key, value in item.items():
        normalized_key = normalize_signal_text(key)

        if any(
            normalize_signal_text(target) == normalized_key
            for target in classification_keys
        ):
            candidate_values.append(value)

    # 키 이름 자체에 분류가 포함된 경우도 검사
    candidate_values.extend(item.keys())

    combined = " ".join(
        normalize_signal_text(value)
        for value in candidate_values
    )

    if (
        "redflag" in combined
        or "위험신호" in combined
        or combined == "red"
    ):
        return "red_flag"

    if (
        "monitoring" in combined
        or "monitoringsignal" in combined
        or "모니터링" in combined
        or "유의사항" in combined
    ):
        return "monitoring"

    return None


def extract_signal_items(data):
    """
    JSON 구조와 관계없이 전체를 재귀 탐색하여
    실제 규칙 결과 딕셔너리를 수집한다.
    """
    red_flags = []
    monitoring = []
    seen = set()

    def append_unique(target, item):
        fingerprint = json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        if fingerprint not in seen:
            seen.add(fingerprint)
            target.append(item)

    def walk(value, parent_key=""):
        if isinstance(value, dict):
            classification = classify_signal_item(value)

            if classification == "red_flag":
                append_unique(red_flags, value)

            elif classification == "monitoring":
                append_unique(monitoring, value)

            for key, child in value.items():
                normalized_key = normalize_signal_text(key)

                # 명시적인 red flag 목록
                if (
                    "redflag" in normalized_key
                    and isinstance(child, list)
                ):
                    for item in child:
                        if isinstance(item, dict):
                            append_unique(red_flags, item)

                # 명시적인 monitoring 목록
                if (
                    (
                        "monitoring" in normalized_key
                        or "모니터링" in normalized_key
                    )
                    and isinstance(child, list)
                ):
                    for item in child:
                        if isinstance(item, dict):
                            append_unique(monitoring, item)

                walk(child, normalized_key)

        elif isinstance(value, list):
            for child in value:
                walk(child, parent_key)

    walk(data)

    return red_flags, monitoring


def find_numeric_count(data, target_terms):
    """
    JSON에 저장된 명시적인 count 값도 보조적으로 찾는다.
    """
    found = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = normalize_signal_text(key)

                if any(
                    normalize_signal_text(term) in normalized_key
                    for term in target_terms
                ):
                    if isinstance(child, bool):
                        pass

                    elif isinstance(child, (int, float)):
                        found.append(int(child))

                    elif isinstance(child, str):
                        match = re.fullmatch(
                            r"\s*(\d+)\s*(?:개)?\s*",
                            child,
                        )

                        if match:
                            found.append(int(match.group(1)))

                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)

    return found[0] if found else None



def count_signals(data):
    if not isinstance(data, dict):
        return 0, 0

    red_count = data.get("red_flag_count")
    monitoring_count = data.get(
        "monitoring_signal_count"
    )

    if red_count is None:
        red_count = len(
            data.get("red_flags", [])
        )

    if monitoring_count is None:
        monitoring_count = len(
            data.get("monitoring_signals", [])
        )

    return int(red_count), int(monitoring_count)


def first_nonempty(item, keys, default=""):
    if not isinstance(item, dict):
        return default

    for key in keys:
        if key in item:
            value = item.get(key)

            if value is None:
                continue

            if isinstance(value, str):
                if value.strip():
                    return value.strip()

            elif isinstance(value, (int, float)):
                return str(value)

            elif isinstance(value, list):
                if value:
                    return value

            elif isinstance(value, dict):
                if value:
                    return value

    return default


def ensure_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return [item for item in value if item not in [None, "", []]]

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []

        # 줄바꿈 기준 분리 시도
        if "\\n" in text:
            return [x.strip("-• ").strip() for x in text.split("\\n") if x.strip()]

        return [text]

    return [str(value)]


def render_chip_list(values, background="#f2f4f7", color="#344054"):
    values = ensure_list(values)

    if not values:
        return '<span style="color:#98a2b3; font-size:13px;">표시 정보 없음</span>'

    chips = []
    for value in values[:6]:
        chips.append(
            f"""
            <span style="
                display:inline-block;
                padding:6px 10px;
                border-radius:999px;
                background:{background};
                color:{color};
                font-size:12px;
                font-weight:600;
                margin:0 6px 6px 0;
            ">{value}</span>
            """
        )

    return "".join(chips)


def render_list_html(values, empty_text="표시 정보 없음"):
    values = ensure_list(values)

    if not values:
        return f'<div style="color:#98a2b3; font-size:13px;">{empty_text}</div>'

    bullets = []
    for value in values[:5]:
        bullets.append(
            f"""
            <li style="margin-bottom:8px; line-height:1.6;">
                {value}
            </li>
            """
        )

    return f'<ul style="margin:8px 0 0 18px; padding:0;">{"".join(bullets)}</ul>'


def normalize_issue(item, fallback_title):
    title = first_nonempty(
        item,
        [
            "title",
            "headline",
            "summary_title",
            "issue_title",
            "red_flag_name",
            "rule_name",
            "name",
        ],
        fallback_title,
    )

    risk_group = first_nonempty(
        item,
        [
            "risk_group",
            "risk_category",
            "category",
            "risk_type",
        ],
        "General",
    )

    basis = first_nonempty(
        item,
        [
            "basis",
            "evidence",
            "rationale",
            "observed_fact",
            "observed_facts",
            "fact",
            "reason",
            "trigger_reason",
            "rule_summary",
            "description",
        ],
        "세부 근거는 원본 JSON 및 계산 결과를 함께 확인하세요.",
    )

    meaning = first_nonempty(
        item,
        [
            "meaning",
            "risk_meaning",
            "why_it_matters",
            "implication",
            "interpretation",
        ],
        "추가 검토가 필요한 영역으로 해석됩니다.",
    )

    normal_causes = first_nonempty(
        item,
        [
            "possible_normal_causes",
            "normal_causes",
            "possible_causes",
            "business_causes",
        ],
        [],
    )

    risk_causes = first_nonempty(
        item,
        [
            "possible_risks",
            "possible_audit_risks",
            "risk_causes",
            "possible_accounting_risk",
            "possible_fraud_or_error_risk",
        ],
        [],
    )

    assertions = first_nonempty(
        item,
        [
            "assertions",
            "relevant_assertions",
            "financial_statement_assertions",
        ],
        [],
    )

    questions = first_nonempty(
        item,
        [
            "interview_questions",
            "questions",
            "question_list",
        ],
        [],
    )

    evidence_requests = first_nonempty(
        item,
        [
            "requested_evidence",
            "supporting_evidence",
            "documents",
            "requested_documents",
            "follow_up_evidence",
            "evidence_request",
        ],
        [],
    )

    follow_up = first_nonempty(
        item,
        [
            "follow_up_procedures",
            "audit_procedures",
            "next_actions",
        ],
        [],
    )

    return {
        "title": title,
        "risk_group": risk_group,
        "basis": basis,
        "meaning": meaning,
        "normal_causes": ensure_list(normal_causes),
        "risk_causes": ensure_list(risk_causes),
        "assertions": ensure_list(assertions),
        "questions": ensure_list(questions),
        "evidence_requests": ensure_list(evidence_requests),
        "follow_up": ensure_list(follow_up),
    }


def render_priority_card(item, index, badge_text, accent="#d92d20"):
    normalized = normalize_issue(item, f"우선 검토 이슈 {index}")

    return f"""
    <div style="
        border:1px solid #eaecf0;
        border-left:6px solid {accent};
        border-radius:16px;
        padding:18px;
        background:#ffffff;
        box-shadow:0 1px 3px rgba(16,24,40,0.06);
        margin-bottom:14px;
    ">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:10px;">
            <div>
                <div style="font-size:12px; font-weight:700; color:{accent}; margin-bottom:6px;">
                    {badge_text}
                </div>
                <div style="font-size:20px; font-weight:800; color:#101828; line-height:1.35;">
                    {index}. {normalized["title"]}
                </div>
            </div>
            <div style="
                padding:6px 10px;
                border-radius:999px;
                background:#f8f9fc;
                color:#344054;
                font-size:12px;
                font-weight:700;
                white-space:nowrap;
            ">
                {normalized["risk_group"]}
            </div>
        </div>

        <div style="
            background:#f8fafc;
            border:1px solid #e4e7ec;
            border-radius:12px;
            padding:14px;
            margin:12px 0;
        ">
            <div style="font-size:13px; font-weight:800; color:#475467; margin-bottom:6px;">
                데이터 근거
            </div>
            <div style="font-size:14px; color:#101828; line-height:1.7;">
                {normalized["basis"]}
            </div>
        </div>

        <div style="
            background:#fff7ed;
            border:1px solid #fed7aa;
            border-radius:12px;
            padding:14px;
            margin:12px 0;
        ">
            <div style="font-size:13px; font-weight:800; color:#9a3412; margin-bottom:6px;">
                왜 지금 확인해야 하나
            </div>
            <div style="font-size:14px; color:#7c2d12; line-height:1.7;">
                {normalized["meaning"]}
            </div>
        </div>

        <div style="margin-top:14px;">
            <div style="font-size:13px; font-weight:800; color:#475467; margin-bottom:8px;">
                관련 재무제표 주장
            </div>
            <div>{render_chip_list(normalized["assertions"], background="#eef4ff", color="#175cd3")}</div>
        </div>
    </div>
    """


def render_action_card(item, index, accent="#175cd3"):
    normalized = normalize_issue(item, f"우선 검토 이슈 {index}")

    return f"""
    <div style="
        border:1px solid #d0d5dd;
        border-radius:16px;
        padding:18px;
        background:#ffffff;
        margin-bottom:14px;
        box-shadow:0 1px 3px rgba(16,24,40,0.06);
    ">
        <div style="font-size:18px; font-weight:800; color:#101828; margin-bottom:12px;">
            {index}. {normalized["title"]}
        </div>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
            <div style="
                border:1px solid #dbeafe;
                background:#eff6ff;
                border-radius:12px;
                padding:14px;
            ">
                <div style="font-size:13px; font-weight:800; color:#1d4ed8; margin-bottom:8px;">
                    인터뷰 질문
                </div>
                <div style="font-size:14px; color:#1e3a8a;">
                    {render_list_html(normalized["questions"], empty_text="질문 정보 없음")}
                </div>
            </div>

            <div style="
                border:1px solid #dcfce7;
                background:#f0fdf4;
                border-radius:12px;
                padding:14px;
            ">
                <div style="font-size:13px; font-weight:800; color:#15803d; margin-bottom:8px;">
                    요청 자료 / 증빙
                </div>
                <div style="font-size:14px; color:#166534;">
                    {render_list_html(normalized["evidence_requests"], empty_text="요청자료 정보 없음")}
                </div>
            </div>
        </div>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px;">
            <div style="
                border:1px solid #eaecf0;
                background:#fcfcfd;
                border-radius:12px;
                padding:14px;
            ">
                <div style="font-size:13px; font-weight:800; color:#475467; margin-bottom:8px;">
                    가능한 정상적 원인
                </div>
                <div style="font-size:14px; color:#344054;">
                    {render_list_html(normalized["normal_causes"], empty_text="표시 정보 없음")}
                </div>
            </div>

            <div style="
                border:1px solid #fecdca;
                background:#fef3f2;
                border-radius:12px;
                padding:14px;
            ">
                <div style="font-size:13px; font-weight:800; color:#b42318; margin-bottom:8px;">
                    가능한 회계·감사 위험
                </div>
                <div style="font-size:14px; color:#912018;">
                    {render_list_html(normalized["risk_causes"], empty_text="표시 정보 없음")}
                </div>
            </div>
        </div>
    </div>
    """


def render_monitoring_card(item, index):
    normalized = normalize_issue(item, f"모니터링 포인트 {index}")

    return f"""
    <div style="
        border:1px solid #f2f4f7;
        border-left:5px solid #f79009;
        border-radius:14px;
        padding:16px;
        background:#ffffff;
        margin-bottom:12px;
    ">
        <div style="font-size:16px; font-weight:800; color:#101828; margin-bottom:6px;">
            {index}. {normalized["title"]}
        </div>
        <div style="font-size:13px; color:#667085; margin-bottom:8px;">
            위험군: {normalized["risk_group"]}
        </div>
        <div style="font-size:14px; color:#344054; line-height:1.7;">
            <strong>근거:</strong> {normalized["basis"]}
        </div>
    </div>
    """




def build_rich_report_html(
    company,
    analysis_data,
    years,
    red_count,
    monitoring_count,
):
    import html

    def esc(value):
        return html.escape(
            str(value if value is not None else "")
        )

    def as_list(value):
        if value is None:
            return []

        if isinstance(value, list):
            return [
                item
                for item in value
                if item not in [None, ""]
            ]

        return [value]

    def bullet_list(values, empty_text="정보 없음"):
        values = as_list(values)

        if not values:
            return (
                '<div class="empty-value">'
                + esc(empty_text)
                + "</div>"
            )

        return (
            '<ul class="report-list">'
            + "".join(
                f"<li>{esc(value)}</li>"
                for value in values
            )
            + "</ul>"
        )

    def assertion_chips(values):
        values = as_list(values)

        if not values:
            return (
                '<span class="empty-value">'
                '관련 주장 정보 없음'
                '</span>'
            )

        return "".join(
            f'<span class="assertion-chip">'
            f'{esc(value)}</span>'
            for value in values
        )

    top_3 = analysis_data.get(
        "top_3",
        [],
    )

    monitoring_signals = analysis_data.get(
        "monitoring_signals",
        [],
    )

    if not top_3:
        all_results = analysis_data.get(
            "all_results",
            [],
        )

        top_3 = sorted(
            all_results,
            key=lambda item: (
                not bool(item.get("triggered")),
                -float(
                    item.get(
                        "priority_score",
                        0,
                    )
                ),
            ),
        )[:3]

    top_ids = {
        item.get("flag_id")
        for item in top_3
    }

    remaining_monitoring = [
        item
        for item in monitoring_signals
        if item.get("flag_id") not in top_ids
    ]

    remaining_monitoring = sorted(
        remaining_monitoring,
        key=lambda item: -float(
            item.get("priority_score", 0)
        ),
    )

    def priority_card(item, index):
        triggered = bool(
            item.get("triggered")
        )

        badge_class = (
            "red-badge"
            if triggered
            else "monitoring-badge"
        )

        border_class = (
            "priority-red"
            if triggered
            else "priority-monitoring"
        )

        return f"""
        <div class="priority-card {border_class}">
            <div class="priority-header">
                <div>
                    <span class="signal-badge {badge_class}">
                        {esc(item.get("status", "Monitoring Signal"))}
                    </span>

                    <div class="priority-title">
                        {index}. {esc(item.get("title"))}
                    </div>
                </div>

                <div class="priority-score">
                    우선순위
                    <strong>
                        {esc(item.get("priority_score", "-"))}
                    </strong>
                </div>
            </div>

            <div class="card-meta-row">
                <span>
                    위험군
                    <strong>{esc(item.get("risk_family", "-"))}</strong>
                </span>

                <span>
                    규칙
                    <strong>{esc(item.get("flag_id", "-"))}</strong>
                </span>
            </div>

            <div class="fact-box">
                <div class="box-label">관측된 사실</div>
                <div class="box-text">
                    {esc(
                        item.get(
                            "observed_fact",
                            item.get("evidence", ""),
                        )
                    )}
                </div>
            </div>

            <div class="meaning-box">
                <div class="box-label">왜 확인해야 하나</div>
                <div class="box-text">
                    {esc(item.get("interpretation", ""))}
                </div>
            </div>

            <div class="assertion-area">
                <div class="box-label">관련 재무제표 주장</div>
                <div>
                    {assertion_chips(item.get("assertions"))}
                </div>
            </div>
        </div>
        """

    def action_card(item, index):
        return f"""
        <div class="action-card">
            <div class="action-card-title">
                {index}. {esc(item.get("title"))}
            </div>

            <div class="action-grid">
                <div class="action-panel question-panel">
                    <div class="action-label">
                        경영진 인터뷰 질문
                    </div>

                    {bullet_list(
                        item.get(
                            "interview_questions",
                            item.get("interview_question"),
                        ),
                        "인터뷰 질문이 없습니다.",
                    )}
                </div>

                <div class="action-panel document-panel">
                    <div class="action-label">
                        요청자료 및 증빙
                    </div>

                    {bullet_list(
                        item.get(
                            "evidence_requests",
                            item.get("evidence_request"),
                        ),
                        "요청자료가 없습니다.",
                    )}
                </div>
            </div>

            <div class="action-grid lower-grid">
                <div class="action-panel normal-panel">
                    <div class="action-label">
                        가능한 정상적 사업 원인
                    </div>

                    {bullet_list(
                        item.get("possible_normal_causes"),
                        "정상 원인 정보가 없습니다.",
                    )}
                </div>

                <div class="action-panel risk-panel">
                    <div class="action-label">
                        잠재 회계·감사 위험
                    </div>

                    {bullet_list(
                        item.get("possible_audit_risks"),
                        "감사위험 정보가 없습니다.",
                    )}
                </div>
            </div>

            <div class="procedure-panel">
                <div class="action-label">
                    후속 감사절차
                </div>

                {bullet_list(
                    item.get("follow_up_procedures"),
                    "후속절차 정보가 없습니다.",
                )}
            </div>
        </div>
        """

    def monitoring_card(item, index):
        return f"""
        <div class="monitoring-card">
            <div class="monitoring-card-header">
                <div class="monitoring-title">
                    {index}. {esc(item.get("title"))}
                </div>

                <div class="monitoring-score">
                    점수 {esc(item.get("priority_score", "-"))}
                </div>
            </div>

            <div class="monitoring-family">
                {esc(item.get("risk_family", "-"))}
            </div>

            <div class="monitoring-fact">
                <strong>관측 사실</strong><br>
                {esc(
                    item.get(
                        "observed_fact",
                        item.get("evidence", ""),
                    )
                )}
            </div>

            <div class="monitoring-meaning">
                <strong>검토 의미</strong><br>
                {esc(item.get("interpretation", ""))}
            </div>
        </div>
        """

    priority_html = "".join(
        priority_card(item, index)
        for index, item in enumerate(
            top_3,
            start=1,
        )
    )

    action_html = "".join(
        action_card(item, index)
        for index, item in enumerate(
            top_3,
            start=1,
        )
    )

    monitoring_html = "".join(
        monitoring_card(item, index)
        for index, item in enumerate(
            remaining_monitoring,
            start=1,
        )
    )

    if not monitoring_html:
        monitoring_html = """
        <div class="empty-section">
            Top 3 이외의 추가 Monitoring Signal이 없습니다.
        </div>
        """

    years_text = " · ".join(
        str(year)
        for year in years
    )

    rule_count = analysis_data.get(
        "rule_count",
        len(
            analysis_data.get(
                "all_results",
                [],
            )
        ),
    )

    return f"""
    <div class="audit-report-wrap">

        <div class="report-hero">
            <div class="report-eyebrow">
                AUDIT PRE-ANALYSIS REPORT
            </div>

            <div class="report-title">
                {esc(company)} Audit Red Flag Report
            </div>

            <div class="report-meta">
                분석기간 {esc(years_text)}
                <span class="meta-divider">|</span>
                전체 규칙 {esc(rule_count)}개
                <span class="meta-divider">|</span>
                Red Flag {esc(red_count)}개
                <span class="meta-divider">|</span>
                Monitoring Signal {esc(monitoring_count)}개
            </div>
        </div>

        <section class="report-section">
            <div class="section-title">
                Top 3 우선 검토 영역
            </div>

            <div class="section-description">
                실제 발동된 Red Flag를 우선 배치하고,
                나머지는 우선순위 점수가 높은 Monitoring Signal로
                구성했습니다.
            </div>

            {priority_html}
        </section>

        <section class="report-section">
            <div class="section-title">
                인터뷰 질문 및 요청자료
            </div>

            <div class="section-description">
                이슈별 경영진 질문, 요청자료, 가능한 사업 원인,
                잠재 감사위험 및 후속절차입니다.
            </div>

            {action_html}
        </section>

        <section class="report-section">
            <div class="section-title">
                추가 모니터링 포인트
            </div>

            {monitoring_html}
        </section>

        <div class="report-disclaimer">
            <strong>해석상 주의</strong><br>
            {esc(DISCLAIMER)}
        </div>

    </div>
    """


def build_status_html(
    company,
    mode,
    red_count,
    monitoring_count,
    years,
):
    return f"""
    <div class="status-grid">
        <div class="status-card">
            <div class="status-label">기업</div>
            <div class="status-value company-value">{company}</div>
        </div>

        <div class="status-card red-card">
            <div class="status-label">Red Flag</div>
            <div class="status-value">{red_count}</div>
        </div>

        <div class="status-card monitoring-card">
            <div class="status-label">Monitoring Signal</div>
            <div class="status-value">{monitoring_count}</div>
        </div>

        <div class="status-card">
            <div class="status-label">분석 연도</div>
            <div class="status-value year-value">
                {" · ".join(years)}
            </div>
        </div>
    </div>

    <div class="mode-box">
        <strong>분석 모드</strong><br>
        {mode}
    </div>
    """


def error_outputs(error):
    message_html = f"""
    <div style="padding:16px; border:1px solid #fecdca; background:#fef3f2; border-radius:14px;">
        <div style="font-weight:800; color:#b42318; margin-bottom:8px;">
            분석 실행 실패
        </div>
        <div style="color:#344054; font-size:14px; line-height:1.6;">
            <strong>{type(error).__name__}</strong><br><br>
            {str(error).replace(chr(10), "<br>")}
        </div>
    </div>
    """

    return (
        """
        <div class="error-box">
            분석 실행 실패
        </div>
        """,
        pd.DataFrame(),
        message_html,
        None,
        None,
        None,
    )


# =========================================================
# 실무 감사 분석
# =========================================================
def run_hybrid_web(
    company,
    corp_code,
    audit_year,
    current_file,
):
    try:
        company = str(company or "").strip()
        corp_code = str(corp_code or "").strip()
        audit_year = int(audit_year)

        current_path = file_path(current_file)

        if not company:
            raise ValueError("기업명을 입력해주세요.")

        if not corp_code:
            raise ValueError("DART 고유번호를 입력해주세요.")

        if current_path is None or not current_path.exists():
            raise ValueError(
                "당기 미감사 CSV를 업로드해주세요."
            )

        current_df, year_columns = validate_standard_csv(
            current_path,
            expected_year_count=1,
        )

        expected_year = str(audit_year)

        if year_columns != [expected_year]:
            raise ValueError(
                f"당기자료 연도 컬럼은 {expected_year}여야 합니다. "
                f"현재: {year_columns}"
            )

        command = [
            sys.executable,
            "-u",
            str(HYBRID_PATH),
            "--company",
            company,
            "--corp-code",
            corp_code,
            "--audit-year",
            str(audit_year),
            "--current-file",
            str(current_path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=900,
        )

        if result.returncode != 0:
            error_text = (
                result.stderr.strip()
                or result.stdout.strip()
            )

            raise RuntimeError(
                "실무 감사 결합 분석에 실패했습니다.\n\n"
                + error_text[-5000:]
            )

        combined_csv = extract_path_from_stdout(
            result.stdout,
            "결합 CSV",
        )

        json_path = extract_path_from_stdout(
            result.stdout,
            "JSON",
        )

        markdown_path = extract_path_from_stdout(
            result.stdout,
            "보고서",
        )

        if not combined_csv or not combined_csv.exists():
            raise FileNotFoundError(
                "결합 CSV 경로를 확인하지 못했습니다."
            )

        if not json_path or not json_path.exists():
            raise FileNotFoundError(
                "분석 JSON 경로를 확인하지 못했습니다."
            )

        if (
            not markdown_path
            or not markdown_path.exists()
        ):
            raise FileNotFoundError(
                "분석 보고서 경로를 확인하지 못했습니다."
            )

        combined_df, final_years = (
            validate_standard_csv(
                combined_csv,
                expected_year_count=3,
            )
        )

        analysis_data, report = (
            read_json_and_report(
                json_path,
                markdown_path,
            )
        )

        red_count, monitoring_count = (
            count_signals(analysis_data)
        )

        report = build_rich_report_html(
            company,
            analysis_data,
            years,
            red_count,
            monitoring_count,
        )

        status = build_status_html(
            company=company,
            mode=(
                "연말감사 실무 결합 분석 "
                "(전전기·전기 DART + 당기 미감사 자료)"
            ),
            red_count=red_count,
            monitoring_count=monitoring_count,
            years=final_years,
        )

        return (
            status,
            combined_df,
            report,
            str(combined_csv),
            str(json_path),
            str(markdown_path),
        )

    except Exception as error:
        return error_outputs(error)


# =========================================================
# 공개자료 DART 분석
# =========================================================
def run_public_dart_web(
    company,
    corp_code,
):
    try:
        company = str(company or "").strip()
        corp_code = str(corp_code or "").strip()

        if not company:
            raise ValueError("기업명을 입력해주세요.")

        if not corp_code:
            raise ValueError("DART 고유번호를 입력해주세요.")

        command = [
            sys.executable,
            "-u",
            str(DART_PIPELINE_PATH),
            "--company",
            company,
            "--corp-code",
            corp_code,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=900,
        )

        if result.returncode != 0:
            error_text = (
                result.stderr.strip()
                or result.stdout.strip()
            )

            raise RuntimeError(
                "DART 자동수집 분석에 실패했습니다.\n\n"
                + error_text[-5000:]
            )

        csv_path = extract_path_from_stdout(
            result.stdout,
            "입력 CSV",
        )

        output_dir = extract_path_from_stdout(
            result.stdout,
            "결과 폴더",
        )

        if not csv_path or not csv_path.exists():
            raise FileNotFoundError(
                "DART 생성 CSV 경로를 확인하지 못했습니다."
            )

        if not output_dir or not output_dir.exists():
            raise FileNotFoundError(
                "분석 결과 폴더를 확인하지 못했습니다."
            )

        json_path = find_latest_file(
            output_dir,
            "*.json",
        )

        markdown_path = find_latest_file(
            output_dir,
            "*.md",
        )

        if json_path is None:
            raise FileNotFoundError(
                "분석 JSON이 생성되지 않았습니다."
            )

        if markdown_path is None:
            raise FileNotFoundError(
                "분석 보고서가 생성되지 않았습니다."
            )

        financial_df, years = validate_standard_csv(
            csv_path,
            expected_year_count=3,
        )

        analysis_data, report = read_json_and_report(
            json_path,
            markdown_path,
        )

        red_count, monitoring_count = count_signals(
            analysis_data
        )



        report = build_rich_report_html(


            company,


            analysis_data,


            years,


            red_count,


            monitoring_count,


        )

        status = build_status_html(
            company=company,
            mode="공개자료 DART 3개년 자동분석",
            red_count=red_count,
            monitoring_count=monitoring_count,
            years=years,
        )

        return (
            status,
            financial_df,
            report,
            str(csv_path),
            str(json_path),
            str(markdown_path),
        )

    except Exception as error:
        return error_outputs(error)


# =========================================================
# 표준 CSV 직접 분석
# =========================================================
def run_direct_csv_web(
    company,
    csv_file,
):
    try:
        company = str(company or "").strip() or "Uploaded Company"
        csv_path = file_path(csv_file)

        if csv_path is None or not csv_path.exists():
            raise ValueError(
                "표준 3개년 CSV를 업로드해주세요."
            )

        financial_df, years = validate_standard_csv(
            csv_path,
            expected_year_count=3,
        )

        run_dir = make_run_dir(
            "direct_csv"
        )

        output_dir = run_dir / "outputs"
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = [
            sys.executable,
            "-u",
            str(AGENT_PATH),
            str(csv_path),
            "--company",
            company,
            "--output-dir",
            str(output_dir),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            error_text = (
                result.stderr.strip()
                or result.stdout.strip()
            )

            raise RuntimeError(
                "CSV 직접 분석에 실패했습니다.\n\n"
                + error_text[-5000:]
            )

        json_path = find_latest_file(
            output_dir,
            "*.json",
        )

        markdown_path = find_latest_file(
            output_dir,
            "*.md",
        )

        if json_path is None or markdown_path is None:
            raise FileNotFoundError(
                "Agent 결과 파일이 생성되지 않았습니다."
            )

        analysis_data, report = read_json_and_report(
            json_path,
            markdown_path,
        )

        red_count, monitoring_count = count_signals(
            analysis_data
        )



        report = build_rich_report_html(


            company,


            analysis_data,


            years,


            red_count,


            monitoring_count,


        )

        status = build_status_html(
            company=company,
            mode="표준 3개년 CSV 직접 분석",
            red_count=red_count,
            monitoring_count=monitoring_count,
            years=years,
        )

        return (
            status,
            financial_df,
            report,
            str(csv_path),
            str(json_path),
            str(markdown_path),
        )

    except Exception as error:
        return error_outputs(error)


# =========================================================
# 검증 기업 예시
# =========================================================
def load_verified_demo(company):
    try:
        if company not in VERIFIED_COMPANIES:
            raise ValueError(
                "검증 기업을 선택해주세요."
            )

        slug = VERIFIED_COMPANIES[company]
        company_root = VERIFIED_ROOT / slug

        csv_path = (
            company_root
            / "input"
            / f"{slug}_dart_pipeline_11_accounts.csv"
        )

        json_path = (
            company_root
            / "outputs"
            / f"{slug}_audit_analysis.json"
        )

        markdown_path = (
            company_root
            / "outputs"
            / f"{slug}_audit_report.md"
        )

        for path in [
            csv_path,
            json_path,
            markdown_path,
        ]:
            if not path.exists():
                raise FileNotFoundError(
                    f"검증 파일이 없습니다: {path}"
                )

        financial_df, years = validate_standard_csv(
            csv_path,
            expected_year_count=3,
        )

        analysis_data, report = read_json_and_report(
            json_path,
            markdown_path,
        )

        red_count, monitoring_count = count_signals(
            analysis_data
        )



        report = build_rich_report_html(


            company,


            analysis_data,


            years,


            red_count,


            monitoring_count,


        )

        status = build_status_html(
            company=company,
            mode="사전 검증 완료 포트폴리오 예시",
            red_count=red_count,
            monitoring_count=monitoring_count,
            years=years,
        )

        return (
            status,
            financial_df,
            report,
            str(csv_path),
            str(json_path),
            str(markdown_path),
        )

    except Exception as error:
        return error_outputs(error)


# =========================================================
# UI 공통 출력 영역
# =========================================================
def create_result_area():
    status = gr.HTML()

    with gr.Tabs():
        with gr.Tab("분석 보고서"):
            report = gr.HTML()

        with gr.Tab("3개년 재무데이터"):
            financial_table = gr.Dataframe(
                interactive=False,
                wrap=True,
            )

    with gr.Row():
        csv_download = gr.File(
            label="분석 입력·결합 CSV",
            interactive=False,
        )

        json_download = gr.File(
            label="분석 결과 JSON",
            interactive=False,
        )

        markdown_download = gr.File(
            label="감사 분석 보고서",
            interactive=False,
        )

    return [
        status,
        financial_table,
        report,
        csv_download,
        json_download,
        markdown_download,
    ]


CSS = """
:root {
    --navy-950: #101828;
    --navy-900: #182230;
    --navy-800: #243247;
    --navy-700: #344054;
    --navy-600: #475467;
    --navy-500: #667085;

    --blue-700: #175cd3;
    --blue-600: #1570ef;
    --blue-100: #d1e9ff;
    --blue-50: #eff8ff;

    --red-700: #b42318;
    --red-600: #d92d20;
    --red-100: #fecdca;
    --red-50: #fef3f2;

    --amber-800: #93370d;
    --amber-700: #b54708;
    --amber-600: #dc6803;
    --amber-100: #fedf89;
    --amber-50: #fffaeb;

    --green-700: #027a48;
    --green-100: #abefc6;
    --green-50: #ecfdf3;

    --purple-700: #6941c6;
    --purple-100: #d9d6fe;
    --purple-50: #f4f3ff;

    --gray-700: #344054;
    --gray-600: #475467;
    --gray-500: #667085;
    --gray-400: #98a2b3;
    --gray-300: #d0d5dd;
    --gray-200: #e4e7ec;
    --gray-100: #f2f4f7;
    --gray-50: #f9fafb;

    --surface: #ffffff;
    --canvas: #f5f7fa;
    --border: #e4e7ec;
    --shadow-sm: 0 1px 3px rgba(16, 24, 40, 0.06);
    --shadow-md: 0 8px 24px rgba(16, 24, 40, 0.07);
}


/* =====================================================
   전체 화면
   ===================================================== */
body,
.gradio-container {
    background:
        radial-gradient(
            circle at top right,
            rgba(209, 233, 255, 0.42),
            transparent 30%
        ),
        var(--canvas) !important;
}

.gradio-container {
    max-width: 1240px !important;
    margin: 0 auto !important;
    padding: 24px 18px 42px !important;
    color: var(--navy-950) !important;
}


/* =====================================================
   메인 헤더
   ===================================================== */
.header {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 22px;
    padding: 34px 36px;
    margin-bottom: 18px;
    background:
        linear-gradient(
            135deg,
            #172033 0%,
            #21314a 60%,
            #29476c 100%
        );
    box-shadow: var(--shadow-md);
}

.header::after {
    content: "";
    position: absolute;
    width: 260px;
    height: 260px;
    right: -95px;
    top: -130px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.055);
}

.header-kicker {
    position: relative;
    z-index: 1;
    color: #9ec5ff;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.12em;
    margin-bottom: 10px;
}

.header-title {
    position: relative;
    z-index: 1;
    color: #ffffff;
    font-size: 31px;
    font-weight: 800;
    letter-spacing: -0.035em;
    line-height: 1.3;
    margin-bottom: 12px;
}

.header-subtitle {
    position: relative;
    z-index: 1;
    max-width: 850px;
    color: rgba(255, 255, 255, 0.76);
    font-size: 15px;
    line-height: 1.75;
}

.header-tags {
    position: relative;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 20px;
}

.header-tags span {
    display: inline-block;
    padding: 6px 10px;
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.075);
    color: rgba(255, 255, 255, 0.84);
    font-size: 12px;
    font-weight: 650;
}


/* =====================================================
   안내 영역
   ===================================================== */
.notice {
    padding: 16px 18px;
    border: 1px solid #e8d7b3;
    background: #fffdf7;
    border-radius: 14px;
    margin-bottom: 18px;
    color: var(--gray-600);
    font-size: 13px;
    line-height: 1.7;
}

.notice strong {
    color: var(--navy-800);
}


/* =====================================================
   Gradio 탭과 입력 영역
   ===================================================== */
.tabs {
    background: transparent !important;
}

.tab-nav {
    gap: 6px !important;
    padding: 5px !important;
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    background: rgba(255, 255, 255, 0.72) !important;
    box-shadow: var(--shadow-sm);
}

.tab-nav button {
    border-radius: 10px !important;
    color: var(--gray-500) !important;
    font-weight: 700 !important;
    padding: 10px 15px !important;
}

.tab-nav button.selected {
    border: 1px solid var(--gray-200) !important;
    background: #ffffff !important;
    color: var(--navy-900) !important;
    box-shadow: 0 1px 4px rgba(16, 24, 40, 0.08) !important;
}

.block,
.form {
    border-color: var(--border) !important;
}

input,
textarea,
select {
    border-color: var(--gray-300) !important;
    border-radius: 10px !important;
    background: #ffffff !important;
}

input:focus,
textarea:focus,
select:focus {
    border-color: #84adff !important;
    box-shadow: 0 0 0 3px rgba(132, 173, 255, 0.14) !important;
}

button.primary {
    border: 1px solid #1c3557 !important;
    border-radius: 10px !important;
    background: linear-gradient(
        180deg,
        #29476c 0%,
        #203a5c 100%
    ) !important;
    color: #ffffff !important;
    font-weight: 750 !important;
    box-shadow: 0 2px 5px rgba(23, 43, 77, 0.2) !important;
}

button.primary:hover {
    background: linear-gradient(
        180deg,
        #31557f 0%,
        #28476c 100%
    ) !important;
    transform: translateY(-1px);
}


/* =====================================================
   상단 상태 카드
   ===================================================== */
.status-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 16px 0 14px;
}

.status-card {
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 17px;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
}

.status-label {
    color: var(--gray-500);
    font-size: 12px;
    font-weight: 650;
}

.status-value {
    color: var(--navy-950);
    font-size: 25px;
    font-weight: 800;
    margin-top: 7px;
    letter-spacing: -0.025em;
}

.company-value {
    font-size: 19px;
}

.year-value {
    font-size: 15px;
}

.red-card {
    border-top: 3px solid var(--red-600);
}

.monitoring-card {
    border-top: 3px solid var(--amber-600);
}

.mode-box {
    border: 1px solid #c9d8eb;
    background: #f6f9fc;
    color: #35516f;
    border-radius: 13px;
    padding: 14px 16px;
    line-height: 1.65;
}

.error-box {
    border: 1px solid var(--red-100);
    background: var(--red-50);
    color: var(--red-700);
    border-radius: 13px;
    padding: 16px;
    font-weight: 700;
}


/* =====================================================
   분석 보고서 전체
   ===================================================== */
.audit-report-wrap {
    padding: 4px 2px 20px;
}

.report-hero {
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 25px;
    background:
        linear-gradient(
            135deg,
            #ffffff 0%,
            #f8fafc 100%
        );
    margin-bottom: 26px;
    box-shadow: var(--shadow-sm);
}

.report-eyebrow {
    color: #3b6ea8;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.11em;
    margin-bottom: 8px;
}

.report-title {
    color: var(--navy-950);
    font-size: 27px;
    font-weight: 800;
    letter-spacing: -0.03em;
    line-height: 1.35;
}

.report-meta {
    color: var(--gray-500);
    font-size: 13px;
    margin-top: 11px;
    line-height: 1.7;
}

.meta-divider {
    color: var(--gray-300);
    margin: 0 8px;
}

.report-section {
    margin: 29px 0;
}

.section-title {
    color: var(--navy-950);
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.025em;
    margin-bottom: 6px;
}

.section-description {
    color: var(--gray-500);
    font-size: 13px;
    line-height: 1.65;
    margin-bottom: 16px;
}


/* =====================================================
   Top 3 카드
   ===================================================== */
.priority-card {
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    background: var(--surface);
    margin-bottom: 14px;
    box-shadow: var(--shadow-sm);
}

.priority-red {
    border-left: 5px solid #c73e36;
}

.priority-monitoring {
    border-left: 5px solid #d28a28;
}

.priority-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 14px;
}

.priority-title {
    color: var(--navy-950);
    font-size: 19px;
    font-weight: 800;
    margin-top: 9px;
    line-height: 1.45;
    letter-spacing: -0.02em;
}

.signal-badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 800;
}

.red-badge {
    border: 1px solid #f2c8c4;
    background: #fff7f6;
    color: #a9362f;
}

.monitoring-badge {
    border: 1px solid #ead4a9;
    background: #fffbf2;
    color: #996515;
}

.priority-score {
    min-width: 82px;
    padding: 9px 11px;
    border: 1px solid var(--gray-200);
    border-radius: 11px;
    background: var(--gray-50);
    color: var(--gray-500);
    font-size: 11px;
    text-align: center;
}

.priority-score strong {
    display: block;
    color: var(--navy-900);
    font-size: 19px;
    margin-top: 2px;
}

.card-meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    color: var(--gray-500);
    font-size: 12px;
    margin: 14px 0;
}

.card-meta-row strong {
    color: var(--gray-700);
    margin-left: 5px;
}

.fact-box,
.meaning-box {
    border-radius: 12px;
    padding: 14px 15px;
    margin-top: 11px;
}

.fact-box {
    border: 1px solid var(--gray-200);
    background: #f9fafb;
}

.meaning-box {
    border: 1px solid #d8e2ed;
    background: #f5f8fb;
}

.box-label,
.action-label {
    color: var(--gray-600);
    font-size: 12px;
    font-weight: 800;
    margin-bottom: 7px;
}

.box-text {
    color: var(--navy-900);
    font-size: 14px;
    line-height: 1.75;
}

.assertion-area {
    margin-top: 14px;
}

.assertion-chip {
    display: inline-block;
    padding: 6px 10px;
    margin: 0 6px 6px 0;
    border: 1px solid #d3dfed;
    border-radius: 999px;
    background: #f5f8fc;
    color: #416184;
    font-size: 11px;
    font-weight: 700;
}


/* =====================================================
   질문·자료 카드
   ===================================================== */
.action-card {
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 16px;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
}

.action-card-title {
    color: var(--navy-950);
    font-size: 18px;
    font-weight: 800;
    letter-spacing: -0.02em;
    margin-bottom: 15px;
}

.action-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 13px;
}

.lower-grid {
    margin-top: 13px;
}

.action-panel,
.procedure-panel {
    border-radius: 12px;
    padding: 15px;
}

.question-panel {
    border: 1px solid #ccdaeb;
    background: #f6f9fc;
}

.document-panel {
    border: 1px solid #cfe2d8;
    background: #f7fbf9;
}

.normal-panel {
    border: 1px solid var(--gray-200);
    background: #fafbfc;
}

.risk-panel {
    border: 1px solid #ead1cf;
    background: #fdf8f7;
}

.procedure-panel {
    border: 1px solid #ddd8ef;
    background: #faf9fd;
    margin-top: 13px;
}

.question-panel .action-label {
    color: #315f8e;
}

.document-panel .action-label {
    color: #3d7056;
}

.risk-panel .action-label {
    color: #9b443e;
}

.procedure-panel .action-label {
    color: #635788;
}

.report-list {
    margin: 5px 0 0 18px;
    padding: 0;
    color: var(--gray-700);
    font-size: 13px;
    line-height: 1.7;
}

.report-list li {
    margin-bottom: 7px;
}


/* =====================================================
   추가 모니터링 카드
   ===================================================== */
.monitoring-card {
    border: 1px solid var(--border);
    border-left: 4px solid #c58a34;
    border-radius: 13px;
    padding: 17px;
    background: var(--surface);
    margin-bottom: 11px;
    box-shadow: var(--shadow-sm);
}

.monitoring-card-header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
}

.monitoring-title {
    color: var(--navy-950);
    font-size: 15px;
    font-weight: 800;
}

.monitoring-score {
    color: #9a681d;
    font-size: 11px;
    font-weight: 800;
    white-space: nowrap;
}

.monitoring-family {
    color: var(--gray-500);
    font-size: 11px;
    margin: 6px 0 10px;
}

.monitoring-fact,
.monitoring-meaning {
    color: var(--gray-700);
    font-size: 13px;
    line-height: 1.7;
    margin-top: 8px;
}

.empty-value {
    color: var(--gray-400);
    font-size: 12px;
}

.empty-section {
    border: 1px solid var(--border);
    border-radius: 13px;
    padding: 16px;
    background: var(--surface);
    color: var(--gray-500);
}

.report-disclaimer {
    border: 1px solid var(--border);
    border-radius: 13px;
    padding: 16px;
    background: #f8fafc;
    color: var(--gray-600);
    font-size: 12px;
    line-height: 1.75;
    margin-top: 25px;
}


/* =====================================================
   표와 다운로드 영역
   ===================================================== */
table {
    border-collapse: separate !important;
    border-spacing: 0 !important;
}

thead th {
    background: #f5f7fa !important;
    color: var(--gray-700) !important;
    font-weight: 750 !important;
}

tbody td {
    color: var(--gray-700) !important;
}


/* =====================================================
   반응형
   ===================================================== */
@media (max-width: 800px) {
    .gradio-container {
        padding: 14px 10px 32px !important;
    }

    .header {
        padding: 27px 23px;
        border-radius: 18px;
    }

    .header-title {
        font-size: 25px;
    }

    .status-grid {
        grid-template-columns: repeat(2, 1fr);
    }

    .action-grid {
        grid-template-columns: 1fr;
    }

    .priority-header {
        flex-direction: column;
    }
}
"""
# =========================================================
# Gradio 앱
# =========================================================
with gr.Blocks(
    title="감사 위험분석 및 인터뷰 지원 Agent",
    css=CSS,
) as demo:

    gr.HTML(
        """
        <div class="header">
            <div class="header-kicker">
                AUDIT RISK &amp; INTERVIEW SUPPORT
            </div>

            <div class="header-title">
                감사 위험분석 및 인터뷰 지원 Agent
            </div>

            <div class="header-subtitle">
                전기·전전기 확정 재무정보와 당기 미감사 자료를 결합해
                주요 재무 변동을 식별하고, 감사인이 확인할 질문과 요청자료,
                후속 감사절차를 구조화합니다.
            </div>

            <div class="header-tags">
                <span>3개년 재무분석</span>
                <span>Red Flag</span>
                <span>인터뷰 질문</span>
                <span>요청자료</span>
            </div>
        </div>
        """
    )

    gr.HTML(
        f"""
        <div class="notice">
            <strong>해석상 주의</strong><br>
            {DISCLAIMER}<br><br>
            본 도구는 감사인의 전문적 판단을 대체하지 않습니다.
        </div>
        """
    )

    with gr.Tabs():

        # -------------------------------------------------
        # 1. 실무 감사 분석
        # -------------------------------------------------
        with gr.Tab("실무 감사 분석"):
            gr.Markdown(
                """
### 연말감사 결합 분석

전전기와 전기의 연간 재무정보는 DART에서 수집하고,
당기 미감사 재무자료는 회사 제출 CSV로 입력합니다.

중간감사 또는 분·반기 분석에는 전년 동기 비교자료가
추가로 필요합니다.
                """
            )

            with gr.Row():
                hybrid_company = gr.Textbox(
                    label="기업명",
                    placeholder="예: NAVER",
                )

                hybrid_corp_code = gr.Textbox(
                    label="DART 고유번호",
                    placeholder="예: 00266961",
                )

                hybrid_audit_year = gr.Number(
                    label="감사연도",
                    value=2026,
                    precision=0,
                )

            with gr.Row():
                hybrid_current_file = gr.File(
                    label=(
                        "당기 미감사 CSV "
                        "(Account, 감사연도)"
                    ),
                    file_types=[".csv"],
                )

                current_template_download = gr.File(
                    value=str(CURRENT_TEMPLATE),
                    label="당기자료 업로드 양식",
                    interactive=False,
                )

            hybrid_button = gr.Button(
                "실무 감사 결합 분석 실행",
                variant="primary",
            )

            hybrid_outputs = create_result_area()

            hybrid_button.click(
                fn=run_hybrid_web,
                inputs=[
                    hybrid_company,
                    hybrid_corp_code,
                    hybrid_audit_year,
                    hybrid_current_file,
                ],
                outputs=hybrid_outputs,
                show_progress="full",
            )

        # -------------------------------------------------
        # 2. 공개자료 DART 분석
        # -------------------------------------------------
        with gr.Tab("공개자료 DART 분석"):
            gr.Markdown(
                """
### 공개된 최근 3개년 재무정보 자동분석

기업별 계정명과 XBRL 구조에 따라 일부 기업은
자동수집이 제한될 수 있습니다.
                """
            )

            with gr.Row():
                dart_company = gr.Textbox(
                    label="기업명",
                    placeholder="예: 삼성전자",
                )

                dart_corp_code = gr.Textbox(
                    label="DART 고유번호",
                    placeholder="예: 00126380",
                )

            dart_button = gr.Button(
                "DART 자동수집 및 분석",
                variant="primary",
            )

            dart_outputs = create_result_area()

            dart_button.click(
                fn=run_public_dart_web,
                inputs=[
                    dart_company,
                    dart_corp_code,
                ],
                outputs=dart_outputs,
                show_progress="full",
            )

        # -------------------------------------------------
        # 3. 표준 CSV 직접 분석
        # -------------------------------------------------
        with gr.Tab("표준 CSV 직접 분석"):
            gr.Markdown(
                """
### 3개년 표준 CSV 분석

CSV 구조는 `Account, 연도1, 연도2, 연도3`이며,
11개 표준 계정을 모두 포함해야 합니다.
                """
            )

            direct_company = gr.Textbox(
                label="기업명",
                placeholder="분석 결과에 표시할 기업명",
            )

            direct_csv = gr.File(
                label="표준 3개년 CSV",
                file_types=[".csv"],
            )

            direct_button = gr.Button(
                "CSV 분석 실행",
                variant="primary",
            )

            direct_outputs = create_result_area()

            direct_button.click(
                fn=run_direct_csv_web,
                inputs=[
                    direct_company,
                    direct_csv,
                ],
                outputs=direct_outputs,
                show_progress="full",
            )

        # -------------------------------------------------
        # 4. 검증 기업 예시
        # -------------------------------------------------
        with gr.Tab("검증 기업 예시"):
            gr.Markdown(
                """
### 즉시 확인 가능한 검증 결과

외부 DART API 호출 없이 사전에 검증한 결과를
바로 확인할 수 있습니다.
                """
            )

            verified_company = gr.Dropdown(
                choices=list(VERIFIED_COMPANIES.keys()),
                value="삼성전자",
                label="검증 기업 선택",
            )

            verified_button = gr.Button(
                "검증 결과 불러오기",
                variant="primary",
            )

            verified_outputs = create_result_area()

            verified_button.click(
                fn=load_verified_demo,
                inputs=[verified_company],
                outputs=verified_outputs,
                show_progress="minimal",
            )

            verified_company.change(
                fn=load_verified_demo,
                inputs=[verified_company],
                outputs=verified_outputs,
                show_progress="minimal",
            )

            demo.load(
                fn=lambda: load_verified_demo("삼성전자"),
                inputs=[],
                outputs=verified_outputs,
                show_progress="hidden",
            )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        show_error=False,
    )
