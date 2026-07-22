
from pathlib import Path
from datetime import datetime
import argparse
import json
import re
import shutil
import subprocess
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

DART_PIPELINE_PATH = SRC_DIR / "hybe_dart_pipeline.py"
AGENT_PATH = SRC_DIR / "generic_runtime_agent.py"

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

DISCLAIMER = (
    "식별된 Red Flag는 오류나 부정의 존재를 의미하는 것이 아니라, "
    "기업 및 환경에 대한 이해와 중요왜곡표시위험 평가를 위해 "
    "추가적인 질문과 검토가 필요한 영역을 의미한다."
)


# =========================================================
# 공통 유틸리티
# =========================================================
def make_company_slug(company_name):
    text = str(company_name or "").strip().lower()
    text = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "company"


def normalize_account_series(series):
    return (
        series.astype(str)
        .str.strip()
    )


def get_year_columns(df):
    return sorted(
        [
            str(column)
            for column in df.columns
            if re.fullmatch(r"\d{4}", str(column))
        ],
        key=int,
    )


def validate_standard_accounts(df, source_name):
    if "Account" not in df.columns:
        raise ValueError(
            f"{source_name}: Account 컬럼이 없습니다."
        )

    accounts = normalize_account_series(
        df["Account"]
    )

    if len(df) != 11:
        raise ValueError(
            f"{source_name}: 계정 행이 11개가 아닙니다. "
            f"현재 {len(df)}개입니다."
        )

    if accounts.duplicated().any():
        duplicates = sorted(
            accounts[accounts.duplicated()].unique()
        )

        raise ValueError(
            f"{source_name}: 중복 계정이 있습니다: "
            + ", ".join(duplicates)
        )

    missing_accounts = sorted(
        set(REQUIRED_ACCOUNTS) - set(accounts)
    )

    unexpected_accounts = sorted(
        set(accounts) - set(REQUIRED_ACCOUNTS)
    )

    if missing_accounts:
        raise ValueError(
            f"{source_name}: 필수 계정이 누락되었습니다: "
            + ", ".join(missing_accounts)
        )

    if unexpected_accounts:
        raise ValueError(
            f"{source_name}: 허용되지 않은 계정이 있습니다: "
            + ", ".join(unexpected_accounts)
        )

    df = df.copy()
    df["Account"] = accounts

    return df


def validate_numeric_columns(df, columns, source_name):
    validated = df.copy()

    for column in columns:
        numeric = pd.to_numeric(
            validated[column],
            errors="coerce",
        )

        invalid = numeric.isna()

        if invalid.any():
            invalid_accounts = (
                validated.loc[invalid, "Account"]
                .astype(str)
                .tolist()
            )

            raise ValueError(
                f"{source_name}: {column} 컬럼에 "
                f"숫자가 아닌 값 또는 결측값이 있습니다: "
                + ", ".join(invalid_accounts)
            )

        validated[column] = numeric

    return validated


# =========================================================
# 당기 회사 제출 자료 검증
# =========================================================
def load_current_year_file(current_file, audit_year):
    current_path = Path(current_file)

    if not current_path.exists():
        raise FileNotFoundError(
            f"당기 자료를 찾을 수 없습니다: {current_path}"
        )

    try:
        df = pd.read_csv(current_path)
    except UnicodeDecodeError:
        df = pd.read_csv(
            current_path,
            encoding="utf-8-sig",
        )

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    df = validate_standard_accounts(
        df,
        "당기 회사 제출 자료",
    )

    non_account_columns = [
        column
        for column in df.columns
        if column != "Account"
    ]

    expected_year = str(audit_year)

    if non_account_columns != [expected_year]:
        raise ValueError(
            "당기 자료는 다음 두 컬럼만 포함해야 합니다: "
            f"Account,{expected_year}\n"
            f"현재 컬럼: {list(df.columns)}"
        )

    df = validate_numeric_columns(
        df,
        [expected_year],
        "당기 회사 제출 자료",
    )

    return df[["Account", expected_year]]


# =========================================================
# DART 공개자료 검증
# =========================================================
def load_public_history_csv(public_csv, audit_year):
    public_path = Path(public_csv)

    if not public_path.exists():
        raise FileNotFoundError(
            f"DART 공개자료 CSV를 찾을 수 없습니다: {public_path}"
        )

    df = pd.read_csv(public_path)

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    df = validate_standard_accounts(
        df,
        "DART 공개자료",
    )

    year_columns = get_year_columns(df)

    prior_years = [
        year
        for year in year_columns
        if int(year) < int(audit_year)
    ]

    prior_years = sorted(
        prior_years,
        key=int,
    )

    if len(prior_years) < 2:
        raise ValueError(
            "감사연도보다 이전인 공개 연도가 "
            "최소 2개 필요합니다.\n"
            f"감사연도: {audit_year}\n"
            f"확인된 공개 연도: {year_columns}"
        )

    selected_years = prior_years[-2:]

    df = validate_numeric_columns(
        df,
        selected_years,
        "DART 공개자료",
    )

    return (
        df[["Account"] + selected_years],
        selected_years,
    )


# =========================================================
# 기업별 DART CSV 탐색
# =========================================================
def find_generated_public_csv(company):
    slug = make_company_slug(company)

    candidates = [
        PROJECT_ROOT
        / "samples"
        / f"{slug}_dart_pipeline_11_accounts.csv",

        PROJECT_ROOT
        / "samples"
        / f"{company}_dart_pipeline_11_accounts.csv",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    all_candidates = sorted(
        (PROJECT_ROOT / "samples").glob(
            "*_dart_pipeline_11_accounts.csv"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    company_normalized = (
        str(company)
        .replace(" ", "")
        .lower()
    )

    for candidate in all_candidates:
        candidate_normalized = (
            candidate.name
            .replace(" ", "")
            .lower()
        )

        if (
            company_normalized in candidate_normalized
            or slug in candidate_normalized
        ):
            return candidate

    raise FileNotFoundError(
        f"{company}의 DART 생성 CSV를 찾지 못했습니다."
    )


# =========================================================
# DART 파이프라인 실행
# =========================================================
def run_dart_pipeline(company, corp_code):
    if not DART_PIPELINE_PATH.exists():
        raise FileNotFoundError(
            f"DART 파이프라인이 없습니다: "
            f"{DART_PIPELINE_PATH}"
        )

    command = [
        sys.executable,
        "-u",
        str(DART_PIPELINE_PATH),
        "--corp-code",
        str(corp_code),
        "--company",
        str(company),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
        )

        raise RuntimeError(
            "DART 공개자료 자동수집에 실패했습니다.\n\n"
            + error_text[-5000:]
        )

    return find_generated_public_csv(
        company
    )


# =========================================================
# 3개년 결합
# =========================================================
def combine_financial_data(
    public_csv,
    current_file,
    audit_year,
    output_csv,
):
    public_df, prior_years = load_public_history_csv(
        public_csv,
        audit_year,
    )

    current_df = load_current_year_file(
        current_file,
        audit_year,
    )

    merged = public_df.merge(
        current_df,
        on="Account",
        how="outer",
        validate="one_to_one",
    )

    final_years = prior_years + [str(audit_year)]

    merged = validate_standard_accounts(
        merged,
        "3개년 결합자료",
    )

    merged = validate_numeric_columns(
        merged,
        final_years,
        "3개년 결합자료",
    )

    account_order = {
        account: index
        for index, account in enumerate(
            REQUIRED_ACCOUNTS
        )
    }

    merged["_order"] = (
        merged["Account"]
        .map(account_order)
    )

    merged = (
        merged
        .sort_values("_order")
        .drop(columns="_order")
        .reset_index(drop=True)
    )

    merged = merged[
        ["Account"] + final_years
    ]

    output_path = Path(output_csv)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    merged.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    return (
        output_path,
        merged,
        final_years,
    )


# =========================================================
# Agent CLI 옵션 자동 확인
# =========================================================
def get_agent_help():
    result = subprocess.run(
        [
            sys.executable,
            str(AGENT_PATH),
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    return (
        result.stdout
        + "\n"
        + result.stderr
    )


def choose_option(help_text, candidates):
    for option in candidates:
        if option in help_text:
            return option

    return None


def build_agent_command(
    input_csv,
    company,
    output_dir,
):
    """
    generic_runtime_agent.py 실행 형식:

    python generic_runtime_agent.py INPUT_CSV
        --company COMPANY
        --output-dir OUTPUT_DIR

    INPUT_CSV는 위치 인자이다.
    """

    if not AGENT_PATH.exists():
        raise FileNotFoundError(
            f"Agent 파일이 없습니다: {AGENT_PATH}"
        )

    command = [
        sys.executable,
        "-u",
        str(AGENT_PATH),
        str(input_csv),
        "--company",
        str(company),
        "--output-dir",
        str(output_dir),
    ]

    return command

def run_agent(
    input_csv,
    company,
    output_dir,
):
    output_path = Path(output_dir)

    output_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = build_agent_command(
        input_csv,
        company,
        output_path,
    )

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
            "Audit Red Flag Agent 실행에 실패했습니다.\n\n"
            + error_text[-5000:]
        )

    json_files = sorted(
        output_path.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    markdown_files = sorted(
        output_path.glob("*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not json_files:
        raise FileNotFoundError(
            f"Agent JSON 결과가 생성되지 않았습니다: "
            f"{output_path}"
        )

    if not markdown_files:
        raise FileNotFoundError(
            f"Agent Markdown 결과가 생성되지 않았습니다: "
            f"{output_path}"
        )

    return {
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "json": json_files[0],
        "markdown": markdown_files[0],
    }



# =========================================================
# 기존 Agent의 고정 연도 구조와 실무 연도 연결
# =========================================================
def prepare_agent_compatible_input(
    combined_csv,
    actual_years,
    input_dir,
):
    """
    기존 generic_runtime_agent는 내부적으로
    2023, 2024, 2025 연도 열을 요구한다.

    실무 자료의 실제 3개 연도를 canonical 연도로 임시 변환한 뒤,
    결과 생성 후 실제 연도로 복원한다.
    """
    canonical_years = [
        "2023",
        "2024",
        "2025",
    ]

    actual_years = [
        str(year)
        for year in actual_years
    ]

    if len(actual_years) != 3:
        raise ValueError(
            "Agent 입력에는 정확히 3개 연도가 필요합니다. "
            f"현재 연도: {actual_years}"
        )

    source_df = pd.read_csv(
        combined_csv
    )

    expected_columns = [
        "Account",
        *actual_years,
    ]

    actual_columns = [
        str(column)
        for column in source_df.columns
    ]

    if actual_columns != expected_columns:
        raise ValueError(
            "결합 CSV 컬럼이 예상과 다릅니다.\n"
            f"예상: {expected_columns}\n"
            f"실제: {actual_columns}"
        )

    year_to_canonical = dict(
        zip(
            actual_years,
            canonical_years,
        )
    )

    canonical_to_actual = {
        canonical: actual
        for actual, canonical
        in year_to_canonical.items()
    }

    agent_df = source_df.rename(
        columns=year_to_canonical
    )

    agent_input_path = (
        Path(input_dir)
        / "agent_input_canonical_3year.csv"
    )

    agent_df.to_csv(
        agent_input_path,
        index=False,
        encoding="utf-8-sig",
    )

    return (
        agent_input_path,
        canonical_to_actual,
    )


def replace_year_tokens_in_text(
    text,
    canonical_to_actual,
):
    """
    금액 속 숫자를 건드리지 않고,
    독립된 4자리 연도 표현만 실제 연도로 복원한다.
    """
    import re

    result = str(text)

    placeholders = {}

    for index, canonical in enumerate(
        canonical_to_actual
    ):
        placeholder = (
            f"__AUDIT_YEAR_PLACEHOLDER_{index}__"
        )

        placeholders[placeholder] = (
            canonical_to_actual[canonical]
        )

        result = re.sub(
            rf"(?<!\d){re.escape(canonical)}(?!\d)",
            placeholder,
            result,
        )

    for placeholder, actual in placeholders.items():
        result = result.replace(
            placeholder,
            str(actual),
        )

    return result


def restore_json_year_labels(
    value,
    canonical_to_actual,
):
    if isinstance(value, dict):
        restored = {}

        for key, child in value.items():
            key_text = str(key)

            if key_text in canonical_to_actual:
                restored_key = canonical_to_actual[
                    key_text
                ]
            else:
                restored_key = (
                    replace_year_tokens_in_text(
                        key_text,
                        canonical_to_actual,
                    )
                )

            restored[restored_key] = (
                restore_json_year_labels(
                    child,
                    canonical_to_actual,
                )
            )

        return restored

    if isinstance(value, list):
        return [
            restore_json_year_labels(
                child,
                canonical_to_actual,
            )
            for child in value
        ]

    if isinstance(value, str):
        return replace_year_tokens_in_text(
            value,
            canonical_to_actual,
        )

    return value


def restore_agent_output_years(
    json_path,
    markdown_path,
    canonical_to_actual,
):
    import json

    json_path = Path(json_path)
    markdown_path = Path(markdown_path)

    with json_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        json_data = json.load(file)

    restored_json = restore_json_year_labels(
        json_data,
        canonical_to_actual,
    )

    with json_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            restored_json,
            file,
            ensure_ascii=False,
            indent=2,
        )

    markdown_text = markdown_path.read_text(
        encoding="utf-8"
    )

    restored_markdown = (
        replace_year_tokens_in_text(
            markdown_text,
            canonical_to_actual,
        )
    )

    markdown_path.write_text(
        restored_markdown,
        encoding="utf-8",
    )



# =========================================================
# 실무 감사 결합 모드 전체 실행
# =========================================================
def run_hybrid_audit(
    company,
    corp_code,
    audit_year,
    current_file,
    public_csv=None,
    skip_dart=False,
):
    audit_year = int(audit_year)
    slug = make_company_slug(company)

    run_id = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    run_root = (
        PROJECT_ROOT
        / "hybrid_audit_runs"
        / slug
        / run_id
    )

    input_dir = run_root / "input"
    output_dir = run_root / "outputs"

    input_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if public_csv:
        selected_public_csv = Path(
            public_csv
        )

    elif skip_dart:
        selected_public_csv = (
            find_generated_public_csv(
                company
            )
        )

    else:
        selected_public_csv = (
            run_dart_pipeline(
                company,
                corp_code,
            )
        )

    copied_current_file = (
        input_dir
        / f"{slug}_{audit_year}_unaudited.csv"
    )

    shutil.copy2(
        current_file,
        copied_current_file,
    )

    combined_csv = (
        input_dir
        / f"{slug}_{audit_year}_hybrid_3year.csv"
    )

    (
        combined_path,
        combined_df,
        final_years,
    ) = combine_financial_data(
        selected_public_csv,
        copied_current_file,
        audit_year,
        combined_csv,
    )

    # 기존 Agent의 고정 연도 구조에 맞춰 내부 입력을 변환한다.
    # 결과 생성 후에는 실제 감사연도로 다시 복원한다.
    (
        agent_input_path,
        canonical_to_actual,
    ) = prepare_agent_compatible_input(
        combined_path,
        final_years,
        input_dir,
    )

    agent_result = run_agent(
        agent_input_path,
        company,
        output_dir,
    )

    restore_agent_output_years(
        agent_result["json"],
        agent_result["markdown"],
        canonical_to_actual,
    )

    metadata = {
        "company": company,
        "corp_code": str(corp_code),
        "audit_year": audit_year,
        "mode": "year_end_hybrid_audit",
        "period_scope": "annual_financial_statements",
        "public_prior_years": final_years[:2],
        "current_unaudited_year": final_years[2],
        "public_csv": str(selected_public_csv),
        "current_file": str(copied_current_file),
        "combined_csv": str(combined_path),
        "agent_internal_input": str(agent_input_path),
        "year_compatibility_mapping": canonical_to_actual,
        "agent_json": str(agent_result["json"]),
        "agent_markdown": str(
            agent_result["markdown"]
        ),
        "created_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "disclaimer": DISCLAIMER,
        "interim_limitation": (
            "본 결합 분석 기능은 연말감사를 위한 "
            "연간 재무자료를 기준으로 한다. "
            "중간감사 또는 분·반기 분석에는 "
            "전년 동기 비교자료가 추가로 필요하다."
        ),
    }

    metadata_path = (
        run_root
        / "hybrid_run_metadata.json"
    )

    with metadata_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return {
        "run_root": run_root,
        "combined_csv": combined_path,
        "combined_df": combined_df,
        "json": agent_result["json"],
        "markdown": agent_result["markdown"],
        "metadata": metadata_path,
        "stdout": agent_result["stdout"],
    }


# =========================================================
# CLI
# =========================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "전전기·전기 DART 자료와 당기 미감사 자료를 "
            "결합하여 Audit Red Flag Agent를 실행합니다."
        )
    )

    parser.add_argument(
        "--company",
        required=True,
    )

    parser.add_argument(
        "--corp-code",
        required=True,
    )

    parser.add_argument(
        "--audit-year",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--current-file",
        required=True,
    )

    parser.add_argument(
        "--public-csv",
        default=None,
    )

    parser.add_argument(
        "--skip-dart",
        action="store_true",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    result = run_hybrid_audit(
        company=args.company,
        corp_code=args.corp_code,
        audit_year=args.audit_year,
        current_file=args.current_file,
        public_csv=args.public_csv,
        skip_dart=args.skip_dart,
    )

    print("=" * 80)
    print("실무 감사 결합 분석 완료")
    print("=" * 80)
    print("기업:", args.company)
    print("감사연도:", args.audit_year)
    print("결합 CSV:", result["combined_csv"])
    print("JSON:", result["json"])
    print("보고서:", result["markdown"])
    print("메타데이터:", result["metadata"])
    print("결과 폴더:", result["run_root"])


if __name__ == "__main__":
    main()
