
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from lxml import etree


DART_BASE_URL = "https://opendart.fss.or.kr/api"

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


ACCOUNT_RULES = {
    "Revenue": {
        "account_ids": [
            "ifrs-full_Revenue",
        ],
        "account_names": [
            "매출액",
            "영업수익",
            "수익(매출액)",
        ],
    },
    "Operating_Profit": {
        "account_ids": [
            "dart_OperatingIncomeLoss",
        ],
        "account_names": [
            "영업이익",
            "영업이익(손실)",
        ],
    },
    "Net_Income": {
        "account_ids": [
            "ifrs-full_ProfitLoss",
        ],
        "account_names": [
            "당기순이익",
            "당기순이익(손실)",
            "연결당기순이익",
        ],
    },
    "Total_Assets": {
        "account_ids": [
            "ifrs-full_Assets",
        ],
        "account_names": [
            "자산총계",
        ],
    },
    "Operating_Cash_Flow": {
        "account_ids": [
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        ],
        "account_names": [
            "영업활동현금흐름",
            "영업활동으로 인한 현금흐름",
        ],
    },
    "Intangible_Assets": {
        "account_ids": [
            "ifrs-full_IntangibleAssetsOtherThanGoodwill",
            "ifrs-full_IntangibleAssetsAndGoodwill",
        ],
        "account_names": [
            "무형자산",
            "무형자산 및 영업권",
        ],
    },
    "Investment_in_Associates": {
        "account_ids": [
            "ifrs-full_InvestmentsInAssociatesAndJointVentures",
            "ifrs-full_InvestmentsInAssociates",
        'ifrs-full_InvestmentAccountedForUsingEquityMethod',
        '관계기업및공동기업 투자',
        '관계기업및공동기업투자',
],
        "account_names": [
            "관계기업 및 공동기업 투자",
            "관계기업투자",
            "관계기업 및 공동기업투자주식",
        ],
    },
    "Accounts_Receivable": {
        "account_ids": [
            "ifrs-full_TradeAndOtherCurrentReceivables",
            "ifrs-full_TradeReceivables",
        ],
        "account_names": [
            "매출채권",
            "매출채권 및 기타채권",
        ],
    },
    "Inventory": {
        "account_ids": [
            "ifrs-full_Inventories",
        ],
        "account_names": [
            "재고자산",
        ],
    },
    "Trade_Payables": {
        "account_ids": [
            "ifrs-full_TradeAndOtherCurrentPayables",
            "ifrs-full_TradePayables",
        ],
        "account_names": [
            "매입채무",
            "매입채무 및 기타채무",
        ],
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "하이브 OpenDART 재무제표와 XBRL 영업권을 "
            "수집해 Audit Red Flag Agent를 실행합니다."
        )
    )

    parser.add_argument(
        "--api-key",
        default=os.getenv("DART_API_KEY"),
        help="OpenDART API Key. 생략 시 DART_API_KEY 환경변수를 사용합니다.",
    )

    parser.add_argument(
        "--corp-code",
        default="01204056",
        help="OpenDART 기업 고유번호. 하이브 기본값: 01204056",
    )

    parser.add_argument(
        "--company",
        default="하이브",
        help="보고서에 표시할 기업명",
    )

    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2023, 2024, 2025],
        help="분석 사업연도",
    )

    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="프로젝트 루트 경로",
    )

    return parser.parse_args()


def request_json(
    endpoint: str,
    params: Dict,
    timeout: int = 60,
) -> Dict:
    response = requests.get(
        f"{DART_BASE_URL}/{endpoint}",
        params=params,
        timeout=timeout,
    )

    response.raise_for_status()
    data = response.json()

    status = data.get("status")

    if status != "000":
        raise RuntimeError(
            f"OpenDART API 오류: "
            f"status={status}, message={data.get('message')}"
        )

    return data


def clean_amount(value) -> Optional[int]:
    if value is None:
        return None

    text = str(value).strip()

    if text in {"", "-", "None", "nan"}:
        return None

    text = text.replace(",", "")

    try:
        return int(float(text))
    except ValueError:
        return None


def fetch_financial_statements(
    api_key: str,
    corp_code: str,
    year: int,
) -> pd.DataFrame:
    data = request_json(
        "fnlttSinglAcntAll.json",
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",
            "fs_div": "CFS",
        },
    )

    rows = data.get("list", [])

    if not rows:
        raise RuntimeError(
            f"{year}년 연결재무제표 데이터가 없습니다."
        )

    df = pd.DataFrame(rows)
    df["business_year"] = year

    return df


def select_account_row(
    df: pd.DataFrame,
    standard_account: str,
) -> Optional[pd.Series]:
    rule = ACCOUNT_RULES[standard_account]

    id_matches = df[
        df["account_id"].fillna("").isin(
            rule["account_ids"]
        )
    ]

    if not id_matches.empty:
        return id_matches.iloc[0]

    account_name_series = (
        df["account_nm"]
        .fillna("")
        .astype(str)
    )

    for account_name in rule["account_names"]:
        name_matches = df[
            account_name_series.str.contains(
                re.escape(account_name),
                regex=True,
                na=False,
            )
        ]

        if not name_matches.empty:
            return name_matches.iloc[0]

    return None


def extract_standard_accounts(
    yearly_data: Dict[int, pd.DataFrame],
) -> pd.DataFrame:
    result_rows = []

    for standard_account in REQUIRED_ACCOUNTS:
        if standard_account == "Goodwill":
            continue

        row = {
            "Account": standard_account,
        }

        for year, df in yearly_data.items():
            selected = select_account_row(
                df,
                standard_account,
            )

            amount = None

            if selected is not None:
                amount = clean_amount(
                    selected.get("thstrm_amount")
                )

            row[str(year)] = amount

        result_rows.append(row)

    return pd.DataFrame(result_rows)


def find_annual_report_receipt(
    api_key: str,
    corp_code: str,
    business_year: int,
) -> str:
    search_start = f"{business_year + 1}0101"
    search_end = f"{business_year + 1}1231"

    data = request_json(
        "list.json",
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": search_start,
            "end_de": search_end,
            "pblntf_ty": "A",
            "page_count": "100",
        },
    )

    reports = data.get("list", [])

    candidates = []

    for report in reports:
        report_name = str(
            report.get("report_nm", "")
        )

        if "사업보고서" not in report_name:
            continue

        if "기재정정" in report_name:
            continue

        candidates.append(report)

    if not candidates:
        raise RuntimeError(
            f"{business_year}년 사업보고서 접수번호를 "
            f"찾지 못했습니다."
        )

    candidates.sort(
        key=lambda item: item.get("rcept_dt", ""),
        reverse=True,
    )

    return candidates[0]["rcept_no"]


def download_xbrl_zip(
    api_key: str,
    receipt_no: str,
    output_zip: Path,
):
    response = requests.get(
        f"{DART_BASE_URL}/fnlttXbrl.xml",
        params={
            "crtfc_key": api_key,
            "rcept_no": receipt_no,
            "reprt_code": "11011",
        },
        timeout=120,
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

    if "json" in content_type:
        error_data = response.json()
        raise RuntimeError(
            f"XBRL 다운로드 오류: {error_data}"
        )

    output_zip.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_zip.write_bytes(response.content)

    if not zipfile.is_zipfile(output_zip):
        preview = response.content[:300]
        raise RuntimeError(
            "다운로드 파일이 ZIP 형식이 아닙니다. "
            f"응답 앞부분: {preview!r}"
        )


def extract_zip(
    zip_path: Path,
    extract_dir: Path,
):
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    extract_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    with zipfile.ZipFile(zip_path, "r") as zip_file:
        zip_file.extractall(extract_dir)


def normalize_context_text(
    context_element,
) -> str:
    text_parts = []

    for element in context_element.iter():
        if element.text:
            value = element.text.strip()

            if value:
                text_parts.append(value)

    return " ".join(text_parts)


def find_contexts(
    xml_root,
) -> Dict[str, str]:
    contexts = {}

    for element in xml_root.iter():
        local_name = etree.QName(element).localname

        if local_name != "context":
            continue

        context_id = element.get("id")

        if not context_id:
            continue

        contexts[context_id] = normalize_context_text(
            element
        )

    return contexts


def extract_goodwill_candidates_from_xml(
    xml_path: Path,
    business_year: int,
) -> List[Dict]:
    parser = etree.XMLParser(
        recover=True,
        huge_tree=True,
    )

    try:
        tree = etree.parse(
            str(xml_path),
            parser,
        )
    except Exception:
        return []

    root = tree.getroot()
    contexts = find_contexts(root)

    candidates = []
    year_end = f"{business_year}-12-31"

    for element in root.iter():
        try:
            local_name = etree.QName(
                element
            ).localname
        except Exception:
            continue

        if local_name.lower() != "goodwill":
            continue

        context_ref = element.get("contextRef")
        unit_ref = element.get("unitRef")

        if not context_ref:
            continue

        value = clean_amount(element.text)

        if value is None:
            continue

        context_text = contexts.get(
            context_ref,
            "",
        )

        lowered_context = context_text.lower()

        if year_end not in context_text:
            continue

        if "consolidatedmember" not in lowered_context:
            continue

        if "separatemember" in lowered_context:
            continue

        if unit_ref and unit_ref.upper() != "KRW":
            continue

        candidates.append(
            {
                "value": value,
                "context_ref": context_ref,
                "context_text": context_text,
                "source_file": str(xml_path),
            }
        )

    return candidates


def score_goodwill_candidate(
    candidate: Dict,
    business_year: int,
) -> int:
    context_text = candidate["context_text"]
    lowered = context_text.lower()

    score = 0

    if f"{business_year}-12-31" in context_text:
        score += 10

    if "consolidatedmember" in lowered:
        score += 10

    excluded_words = [
        "separatemember",
        "cashgeneratingunit",
        "subsidiary",
        "segment",
        "businesscombination",
        "acquisition",
        "disposal",
        "impairment",
        "increase",
        "decrease",
        "movement",
    ]

    for word in excluded_words:
        if word in lowered:
            score -= 5

    token_count = len(
        re.findall(
            r"[A-Za-z0-9:_-]+",
            context_text,
        )
    )

    score -= max(
        token_count - 8,
        0,
    )

    return score


def extract_goodwill_value(
    extract_dir: Path,
    business_year: int,
) -> int:
    all_candidates = []

    for xml_path in extract_dir.rglob("*"):
        if not xml_path.is_file():
            continue

        if xml_path.suffix.lower() not in {
            ".xml",
            ".xbrl",
        }:
            continue

        all_candidates.extend(
            extract_goodwill_candidates_from_xml(
                xml_path,
                business_year,
            )
        )

    if not all_candidates:
        raise RuntimeError(
            f"{business_year}년 XBRL에서 "
            f"Goodwill 후보를 찾지 못했습니다."
        )

    for candidate in all_candidates:
        candidate["score"] = score_goodwill_candidate(
            candidate,
            business_year,
        )

    all_candidates.sort(
        key=lambda item: (
            item["score"],
            item["value"],
        ),
        reverse=True,
    )

    best_score = all_candidates[0]["score"]

    best_candidates = [
        item
        for item in all_candidates
        if item["score"] == best_score
    ]

    unique_values = sorted(
        {
            item["value"]
            for item in best_candidates
        }
    )

    if len(unique_values) != 1:
        preview = [
            {
                "value": item["value"],
                "score": item["score"],
                "context_ref": item["context_ref"],
                "context_text": item["context_text"][:300],
            }
            for item in best_candidates[:10]
        ]

        raise RuntimeError(
            f"{business_year}년 Goodwill 최종 후보가 "
            f"1개 값으로 확정되지 않았습니다.\n"
            f"{json.dumps(preview, ensure_ascii=False, indent=2)}"
        )

    return unique_values[0]


def build_final_csv(
    standard_df: pd.DataFrame,
    goodwill_values: Dict[int, int],
    output_csv: Path,
):
    goodwill_row = {
        "Account": "Goodwill",
    }

    for year, value in goodwill_values.items():
        goodwill_row[str(year)] = value

    final_df = pd.concat(
        [
            standard_df,
            pd.DataFrame([goodwill_row]),
        ],
        ignore_index=True,
    )

    final_df["order"] = final_df["Account"].map(
        {
            account: index
            for index, account
            in enumerate(REQUIRED_ACCOUNTS)
        }
    )

    final_df = (
        final_df
        .sort_values("order")
        .drop(columns=["order"])
        .reset_index(drop=True)
    )

    missing_accounts = sorted(
        set(REQUIRED_ACCOUNTS)
        - set(final_df["Account"])
    )

    value_columns = [
        column
        for column in final_df.columns
        if column != "Account"
    ]

    missing_value_count = int(
        final_df[value_columns]
        .isna()
        .sum()
        .sum()
    )

    if missing_accounts:
        raise RuntimeError(
            f"필수 계정 누락: {missing_accounts}"
        )

    if missing_value_count:
        raise RuntimeError(
            f"최종 CSV 결측값 수: "
            f"{missing_value_count}"
        )

    output_csv.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    final_df.to_csv(
        output_csv,
        index=False,
        encoding="utf-8-sig",
    )

    return final_df


def run_agent(
    project_root: Path,
    company: str,
    input_csv: Path,
    output_dir: Path,
):
    agent_script = (
        project_root
        / "src"
        / "generic_runtime_agent.py"
    )

    if not agent_script.exists():
        raise FileNotFoundError(
            f"Agent 파일이 없습니다: {agent_script}"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(agent_script),
            str(input_csv),
            "--company",
            company,
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    print("\nAgent 표준 출력")
    print(result.stdout)

    if result.stderr:
        print("\nAgent 오류 출력")
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"Agent 실행 실패. "
            f"종료 코드: {result.returncode}"
        )


def main():
    args = parse_args()

    if not args.api_key:
        raise RuntimeError(
            "OpenDART API Key가 없습니다. "
            "--api-key 또는 DART_API_KEY 환경변수를 설정하세요."
        )

    project_root = Path(args.project_root)

    samples_dir = (
        project_root
        / "samples"
    )

    xbrl_root = (
        project_root
        / "dart_xbrl"
        / "hybe_pipeline"
    )

    output_csv = (
        samples_dir
        / f"{args.company.lower().replace(' ', '_')}_dart_pipeline_11_accounts.csv"
    )

    agent_output_dir = (
        project_root
        / f"{args.company.lower().replace(' ', '_')}_pipeline_outputs"
    )

    yearly_data = {}

    print("1. OpenDART 연결재무제표 수집")

    for year in args.years:
        print(f"- {year}년 수집 중")

        yearly_data[year] = fetch_financial_statements(
            args.api_key,
            args.corp_code,
            year,
        )

    print("\n2. 10개 기본 계정 표준화")

    standard_df = extract_standard_accounts(
        yearly_data
    )

    print(
        standard_df.to_string(
            index=False
        )
    )

    print("\n3. 사업보고서 XBRL 다운로드 및 영업권 추출")

    goodwill_values = {}

    for year in args.years:
        print(f"- {year}년 사업보고서 검색")

        receipt_no = find_annual_report_receipt(
            args.api_key,
            args.corp_code,
            year,
        )

        year_dir = xbrl_root / str(year)
        zip_path = year_dir / "xbrl.zip"
        extract_dir = year_dir / "extracted"

        print(
            f"  접수번호: {receipt_no}"
        )

        # 카카오 2025 사업보고서 XBRL 접수번호 예외처리
        KAKAO_2025_VALID_RCEPT_NO = "20260318001423"
        if (
            str(args.company).replace(' ', '') == '카카오'
            and str(year) == '2025'
        ):
            rcept_no = KAKAO_2025_VALID_RCEPT_NO
            print(
                '  카카오 2025 검증 접수번호 적용: '
                + rcept_no
            )

        download_xbrl_zip(
            args.api_key,
            receipt_no,
            zip_path,
        )

        extract_zip(
            zip_path,
            extract_dir,
        )

        goodwill_value = extract_goodwill_value(
            extract_dir,
            year,
        )

        goodwill_values[year] = goodwill_value

        print(
            f"  Goodwill: "
            f"{goodwill_value:,}"
        )

    print("\n4. 최종 11개 계정 CSV 생성")

    final_df = build_final_csv(
        standard_df,
        goodwill_values,
        output_csv,
    )

    print(
        final_df.to_string(
            index=False
        )
    )

    print(
        f"\nCSV 저장: {output_csv}"
    )

    print("\n5. Audit Red Flag Agent 실행")

    run_agent(
        project_root,
        args.company,
        output_csv,
        agent_output_dir,
    )

    print("\n전체 파이프라인 완료")
    print(f"입력 CSV: {output_csv}")
    print(f"결과 폴더: {agent_output_dir}")




# ===== Goodwill extraction override v2 =====
def extract_goodwill_value(
    extract_dir: Path,
    business_year: int,
) -> int:
    """
    XBRL에서 연결재무제표 전체 기준의
    Goodwill 기말잔액을 선택합니다.

    우선순위:
    1. 회사번호 + ConsolidatedMember + 연도말만 존재하는 Context
    2. ReportedAmountMember가 추가된 공시금액 Context
    3. 기존 점수 방식
    """
    all_candidates = []

    for xml_path in extract_dir.rglob("*"):
        if not xml_path.is_file():
            continue

        if xml_path.suffix.lower() not in {
            ".xml",
            ".xbrl",
        }:
            continue

        all_candidates.extend(
            extract_goodwill_candidates_from_xml(
                xml_path,
                business_year,
            )
        )

    if not all_candidates:
        raise RuntimeError(
            f"{business_year}년 XBRL에서 "
            f"Goodwill 후보를 찾지 못했습니다."
        )

    year_end = f"{business_year}-12-31"

    # 1순위:
    # 회사번호 + 연결 기준 + 연도말만 포함된
    # 추가 차원 없는 전체 연결재무제표 Context
    exact_pattern = re.compile(
        rf"^\d{{8}}\s+"
        rf"ifrs-full:ConsolidatedMember\s+"
        rf"{re.escape(year_end)}$"
    )

    exact_candidates = [
        candidate
        for candidate in all_candidates
        if exact_pattern.fullmatch(
            candidate["context_text"].strip()
        )
    ]

    exact_values = sorted(
        {
            candidate["value"]
            for candidate in exact_candidates
        }
    )

    if len(exact_values) == 1:
        print(
            f"  Goodwill 선택 기준: "
            f"추가 차원 없는 연결 기준 Context"
        )
        return exact_values[0]

    # 2순위:
    # ReportedAmountMember는 공시된 장부금액을 의미하므로
    # exact context가 없는 경우 보조 후보로 사용
    reported_candidates = [
        candidate
        for candidate in all_candidates
        if (
            year_end in candidate["context_text"]
            and
            "ifrs-full:ConsolidatedMember"
            in candidate["context_text"]
            and
            "dart:ReportedAmountMember"
            in candidate["context_text"]
            and
            "SeparateMember"
            not in candidate["context_text"]
        )
    ]

    reported_values = sorted(
        {
            candidate["value"]
            for candidate in reported_candidates
        }
    )

    if len(reported_values) == 1:
        print(
            f"  Goodwill 선택 기준: "
            f"ReportedAmountMember"
        )
        return reported_values[0]

    # 3순위: 기존 점수 방식
    for candidate in all_candidates:
        candidate["score"] = score_goodwill_candidate(
            candidate,
            business_year,
        )

    all_candidates.sort(
        key=lambda item: (
            item["score"],
            item["value"],
        ),
        reverse=True,
    )

    best_score = all_candidates[0]["score"]

    best_candidates = [
        item
        for item in all_candidates
        if item["score"] == best_score
    ]

    unique_values = sorted(
        {
            item["value"]
            for item in best_candidates
        }
    )

    if len(unique_values) != 1:
        preview = [
            {
                "value": item["value"],
                "score": item["score"],
                "context_ref": item["context_ref"],
                "context_text": item["context_text"][:300],
            }
            for item in best_candidates[:10]
        ]

        raise RuntimeError(
            f"{business_year}년 Goodwill 최종 후보가 "
            f"1개 값으로 확정되지 않았습니다.\n"
            f"{json.dumps(preview, ensure_ascii=False, indent=2)}"
        )

    return unique_values[0]
# ===== End Goodwill extraction override v2 =====


if __name__ == "__main__":
    main()
