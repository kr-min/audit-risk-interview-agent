from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


YEARS = ["2023", "2024", "2025"]

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

ACCOUNT_ALIASES = {
    "Revenue": [
        "revenue", "sales", "매출액", "영업수익", "수익"
    ],
    "Operating_Profit": [
        "operatingprofit", "operatingincome",
        "영업이익", "영업손익"
    ],
    "Net_Income": [
        "netincome", "profitforperiod",
        "당기순이익", "당기순손익", "연결당기순이익"
    ],
    "Total_Assets": [
        "totalassets", "자산총계", "총자산"
    ],
    "Operating_Cash_Flow": [
        "operatingcashflow",
        "cashflowsfromoperatingactivities",
        "영업활동현금흐름",
        "영업활동으로인한현금흐름"
    ],
    "Intangible_Assets": [
        "intangibleassets", "무형자산"
    ],
    "Goodwill": [
        "goodwill", "영업권"
    ],
    "Investment_in_Associates": [
        "investmentinassociates",
        "investmentsinassociates",
        "관계기업투자",
        "관계기업투자주식",
        "관계기업및공동기업투자"
    ],
    "Accounts_Receivable": [
        "accountsreceivable",
        "tradereceivables",
        "매출채권",
        "매출채권및기타채권"
    ],
    "Inventory": [
        "inventory", "inventories", "재고자산"
    ],
    "Trade_Payables": [
        "tradepayables",
        "accountspayable",
        "매입채무",
        "매입채무및기타채무"
    ],
}

QUESTION_LIBRARY = {
    "RF-001": {
        "question": (
            "매출 성장에도 영업이익률이 하락한 주요 원인은 무엇이며, "
            "일시적 요인과 구조적 요인을 구분할 수 있습니까?"
        ),
        "evidence_request": (
            "부문별 손익자료, 원가 분석표, 주요 비용 증감명세"
        ),
    },
    "RF-002": {
        "question": (
            "영업이익 감소에도 영업현금흐름이 개선된 원인은 "
            "운전자본 변화, 비현금비용 또는 일회성 항목 중 무엇입니까?"
        ),
        "evidence_request": (
            "영업현금흐름 조정내역, 운전자본 증감표, 비현금항목 명세"
        ),
    },
    "RF-003": {
        "question": (
            "수익성 저하가 영업권이 배분된 현금창출단위의 "
            "손상검사 가정에 어떤 영향을 미쳤습니까?"
        ),
        "evidence_request": (
            "영업권 배분표, 손상검사 보고서, 사업계획과 할인율 산정자료"
        ),
    },
    "RF-004": {
        "question": (
            "매출채권 증가가 매출 성장보다 큰 경우, "
            "회수조건이나 연체채권 구성에 변화가 있었습니까?"
        ),
        "evidence_request": (
            "매출채권 연령분석표, 후속입금내역, 주요 고객별 잔액"
        ),
    },
    "RF-005": {
        "question": (
            "재고 증가가 매출 증가를 초과한 원인과 "
            "장기체화 또는 순실현가능가치 하락 가능성은 무엇입니까?"
        ),
        "evidence_request": (
            "재고 연령분석표, 판매실적, 평가충당금 산정자료"
        ),
    },
    "RF-006": {
        "question": (
            "영업이익이 흑자임에도 대규모 순손실이 발생한 "
            "비영업 항목의 구체적 구성은 무엇입니까?"
        ),
        "evidence_request": (
            "금융손익, 지분법손익, 손상차손 및 일회성 항목 명세"
        ),
    },
    "RF-007": {
        "question": (
            "관계기업투자 감소가 처분, 손상, 지분법손실 중 "
            "어떤 요인에서 발생했습니까?"
        ),
        "evidence_request": (
            "관계기업별 장부금액 변동표, 평가자료, 처분계약서"
        ),
    },
    "RF-008": {
        "question": (
            "2년 연속 영업이익률 하락의 핵심 원인과 "
            "향후 회복 계획의 실현 가능성을 어떻게 평가하고 있습니까?"
        ),
        "evidence_request": (
            "연도별 예산 대비 실적, 부문별 마진 분석, 향후 사업계획"
        ),
    },
    "RF-009": {
        "question": (
            "매출 성장에도 순손실이 지속된 원인과 "
            "손실의 반복 가능성은 어떻게 평가하고 있습니까?"
        ),
        "evidence_request": (
            "손실 원인 분석표, 비경상항목 명세, 향후 손익 전망"
        ),
    },
    "RF-010": {
        "question": (
            "자산 활용도는 개선됐지만 ROA가 음수인 원인이 "
            "영업외손실 또는 자산평가 문제와 관련되어 있습니까?"
        ),
        "evidence_request": (
            "자산별 수익성 분석, 손상검사 자료, 영업외손익 명세"
        ),
    },
}


def normalize_text(value: object) -> str:
    text = str(value).strip().lower()
    return re.sub(r"[\s_\-\(\)\[\]·,.]", "", text)


ALIAS_LOOKUP = {}

for standard_account, aliases in ACCOUNT_ALIASES.items():
    ALIAS_LOOKUP[normalize_text(standard_account)] = standard_account

    for alias in aliases:
        ALIAS_LOOKUP[normalize_text(alias)] = standard_account


def standardize_account_name(value: object) -> str | None:
    return ALIAS_LOOKUP.get(normalize_text(value))


def detect_account_column(data: pd.DataFrame) -> str:
    candidates = [
        "account",
        "account_name",
        "계정",
        "계정명",
        "과목",
        "과목명",
    ]

    normalized_columns = {
        normalize_text(column): column
        for column in data.columns
    }

    for candidate in candidates:
        key = normalize_text(candidate)

        if key in normalized_columns:
            return normalized_columns[key]

    raise ValueError(
        "계정명 열을 찾지 못했습니다. "
        "account 또는 계정명 열이 필요합니다."
    )


def parse_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.replace("−", "-", regex=False)
        .replace({"-": "0", "": None, "nan": None})
    )

    return pd.to_numeric(cleaned, errors="coerce")


def load_and_validate(input_path: Path) -> tuple[pd.DataFrame, dict]:
    data = pd.read_csv(input_path, encoding="utf-8-sig")
    data.columns = [str(column).strip() for column in data.columns]

    account_column = detect_account_column(data)

    missing_years = [
        year for year in YEARS
        if year not in data.columns
    ]

    if missing_years:
        raise ValueError(
            f"필수 연도 열이 없습니다: {missing_years}"
        )

    data["original_account"] = data[account_column].astype(str)
    data["account"] = data["original_account"].apply(
        standardize_account_name
    )

    for year in YEARS:
        data[year] = parse_numeric(data[year])

    recognized = data["account"].dropna().tolist()

    missing_accounts = [
        account for account in REQUIRED_ACCOUNTS
        if account not in recognized
    ]

    duplicate_accounts = (
        data.loc[data["account"].notna(), "account"]
        .value_counts()
    )

    duplicate_accounts = duplicate_accounts[
        duplicate_accounts > 1
    ].index.tolist()

    numeric_error_rows = data.loc[
        data["account"].notna()
        & data[YEARS].isna().any(axis=1)
    ]

    validation = {
        "source_file": input_path.name,
        "row_count": int(len(data)),
        "recognized_account_count": int(
            data["account"].notna().sum()
        ),
        "unrecognized_accounts": data.loc[
            data["account"].isna(),
            "original_account",
        ].tolist(),
        "missing_required_accounts": missing_accounts,
        "duplicate_accounts": duplicate_accounts,
        "numeric_error_row_count": int(len(numeric_error_rows)),
        "analysis_ready": bool(
            not missing_accounts
            and not duplicate_accounts
            and numeric_error_rows.empty
        ),
    }

    if not validation["analysis_ready"]:
        raise ValueError(
            "입력 데이터 검증 실패\n"
            + json.dumps(
                validation,
                ensure_ascii=False,
                indent=2,
            )
        )

    analysis_data = data.loc[
        data["account"].notna(),
        ["account", *YEARS],
    ].copy()

    return analysis_data, validation


def get_values(data: pd.DataFrame, account: str) -> dict:
    row = data.loc[data["account"] == account]

    if len(row) != 1:
        raise ValueError(
            f"{account} 계정은 정확히 한 행이어야 합니다."
        )

    return {
        year: float(row.iloc[0][year])
        for year in YEARS
    }


def growth_rate(current: float, previous: float) -> float | None:
    if previous == 0:
        return None

    return (current / previous - 1) * 100


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None

    return numerator / denominator * 100



def run_rules(data: pd.DataFrame) -> tuple[list, dict]:
    values = {
        account: get_values(data, account)
        for account in REQUIRED_ACCOUNTS
    }

    revenue = values["Revenue"]
    op = values["Operating_Profit"]
    net = values["Net_Income"]
    assets = values["Total_Assets"]
    ocf = values["Operating_Cash_Flow"]
    goodwill = values["Goodwill"]
    associates = values["Investment_in_Associates"]
    receivables = values["Accounts_Receivable"]
    inventory = values["Inventory"]

    metrics = {
        "revenue_growth_2025_pct": growth_rate(
            revenue["2025"], revenue["2024"]
        ),
        "receivables_growth_2025_pct": growth_rate(
            receivables["2025"], receivables["2024"]
        ),
        "inventory_growth_2025_pct": growth_rate(
            inventory["2025"], inventory["2024"]
        ),
        "operating_margin_2023_pct": ratio(
            op["2023"], revenue["2023"]
        ),
        "operating_margin_2024_pct": ratio(
            op["2024"], revenue["2024"]
        ),
        "operating_margin_2025_pct": ratio(
            op["2025"], revenue["2025"]
        ),
        "goodwill_to_assets_2025_pct": ratio(
            goodwill["2025"], assets["2025"]
        ),
        "roa_2025_pct": ratio(
            net["2025"], assets["2025"]
        ),
        "asset_turnover_2024": (
            revenue["2024"] / assets["2024"]
        ),
        "asset_turnover_2025": (
            revenue["2025"] / assets["2025"]
        ),
    }

    metrics["operating_margin_change_2025_ppt"] = (
        metrics["operating_margin_2025_pct"]
        - metrics["operating_margin_2024_pct"]
    )

    metrics["receivables_vs_revenue_gap_pct"] = (
        metrics["receivables_growth_2025_pct"]
        - metrics["revenue_growth_2025_pct"]
    )

    metrics["inventory_vs_revenue_gap_pct"] = (
        metrics["inventory_growth_2025_pct"]
        - metrics["revenue_growth_2025_pct"]
    )

    # -----------------------------------------------------
    # 실제 조건과 수치
    # -----------------------------------------------------
    conditions = {
        "RF-001": (
            metrics["revenue_growth_2025_pct"] > 0
            and metrics[
                "operating_margin_change_2025_ppt"
            ] <= -3
        ),
        "RF-002": (
            op["2025"] < op["2024"]
            and ocf["2025"] > ocf["2024"]
        ),
        "RF-003": (
            metrics["goodwill_to_assets_2025_pct"] >= 20
            and metrics[
                "operating_margin_change_2025_ppt"
            ] < 0
        ),
        "RF-004": (
            metrics["receivables_vs_revenue_gap_pct"] >= 10
        ),
        "RF-005": (
            metrics["inventory_vs_revenue_gap_pct"] >= 10
        ),
        "RF-006": (
            op["2025"] > 0
            and net["2025"] < 0
            and abs(net["2025"]) > op["2025"]
        ),
        "RF-007": (
            associates["2025"] < associates["2024"]
            and net["2025"] < 0
        ),
        "RF-008": (
            metrics["operating_margin_2023_pct"]
            > metrics["operating_margin_2024_pct"]
            > metrics["operating_margin_2025_pct"]
        ),
        "RF-009": (
            revenue["2025"] > revenue["2024"]
            and net["2024"] < 0
            and net["2025"] < 0
        ),
        "RF-010": (
            metrics["asset_turnover_2025"]
            > metrics["asset_turnover_2024"]
            and metrics["roa_2025_pct"] < 0
        ),
    }

    evidence = {
        "RF-001": (
            f"매출 증가율 "
            f"{metrics['revenue_growth_2025_pct']:.1f}%, "
            f"영업이익률 변동 "
            f"{metrics['operating_margin_change_2025_ppt']:+.1f}%p"
        ),
        "RF-002": (
            f"영업이익 {op['2024']:,.0f} → {op['2025']:,.0f}, "
            f"영업현금흐름 "
            f"{ocf['2024']:,.0f} → {ocf['2025']:,.0f}"
        ),
        "RF-003": (
            f"영업권/총자산 "
            f"{metrics['goodwill_to_assets_2025_pct']:.1f}%, "
            f"영업이익률 변동 "
            f"{metrics['operating_margin_change_2025_ppt']:+.1f}%p"
        ),
        "RF-004": (
            f"매출채권 증가율 "
            f"{metrics['receivables_growth_2025_pct']:.1f}%, "
            f"매출 증가율 "
            f"{metrics['revenue_growth_2025_pct']:.1f}%, "
            f"격차 "
            f"{metrics['receivables_vs_revenue_gap_pct']:+.1f}%p"
        ),
        "RF-005": (
            f"재고 증가율 "
            f"{metrics['inventory_growth_2025_pct']:.1f}%, "
            f"매출 증가율 "
            f"{metrics['revenue_growth_2025_pct']:.1f}%, "
            f"격차 "
            f"{metrics['inventory_vs_revenue_gap_pct']:+.1f}%p"
        ),
        "RF-006": (
            f"영업이익 {op['2025']:,.0f}, "
            f"당기순손익 {net['2025']:,.0f}"
        ),
        "RF-007": (
            f"관계기업투자 "
            f"{associates['2024']:,.0f} → "
            f"{associates['2025']:,.0f}, "
            f"당기순손익 {net['2025']:,.0f}"
        ),
        "RF-008": (
            f"영업이익률 "
            f"{metrics['operating_margin_2023_pct']:.1f}% → "
            f"{metrics['operating_margin_2024_pct']:.1f}% → "
            f"{metrics['operating_margin_2025_pct']:.1f}%"
        ),
        "RF-009": (
            f"매출 {revenue['2024']:,.0f} → "
            f"{revenue['2025']:,.0f}, "
            f"순손익 {net['2024']:,.0f} → "
            f"{net['2025']:,.0f}"
        ),
        "RF-010": (
            f"자산회전율 "
            f"{metrics['asset_turnover_2024']:.3f} → "
            f"{metrics['asset_turnover_2025']:.3f}, "
            f"ROA {metrics['roa_2025_pct']:.1f}%"
        ),
    }

    # -----------------------------------------------------
    # 규칙별 감사 맥락
    # triggered와 monitoring 문구를 완전히 분리한다.
    # -----------------------------------------------------
    rule_details = {
        "RF-001": {
            "risk_family": "Profitability",
            "triggered_title": "외형 성장에도 수익성이 유의하게 악화",
            "monitoring_title": "매출 성장과 영업이익률 변화 모니터링",
            "triggered_interpretation": (
                "매출이 증가했음에도 영업이익률이 3%p 이상 "
                "하락했습니다. 가격, 제품믹스, 원가 및 비용 인식의 "
                "변화를 분리해 확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "외형 성장과 수익성 악화가 동시에 발생하는 기준에는 "
                "해당하지 않았습니다. 다만 수익성 변화가 일회성인지 "
                "지속 가능한 구조적 변화인지는 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "제품 및 지역 매출 믹스 변화",
                "원재료비와 인건비 변동",
                "신규 사업 초기 비용",
                "프로모션 또는 가격정책 변화",
            ],
            "audit_risks": [
                "매출의 기간귀속 또는 조기인식",
                "비용 누락 또는 분류 오류",
                "충당부채 및 발생비용 과소계상",
            ],
            "assertions": ["발생", "기간귀속", "완전성", "분류"],
            "triggered_questions": [
                "매출 증가에도 영업이익률이 하락한 핵심 원인을 부문별로 설명할 수 있습니까?",
                "수익성 하락 요인 중 일회성과 구조적 요인을 어떻게 구분했습니까?",
            ],
            "monitoring_questions": [
                "영업이익률 변화의 주요 요인은 가격, 판매량, 제품믹스, 원가 중 무엇입니까?",
                "최근 수익성 변화가 향후 사업계획에도 지속될 것으로 판단합니까?",
            ],
            "documents": [
                "부문별 손익자료",
                "매출·원가 브리지 분석표",
                "주요 비용 증감명세",
                "예산 대비 실적 분석",
            ],
            "procedures": [
                "부문별 매출총이익률 추세 분석",
                "주요 매출 및 비용의 기간귀속 테스트",
                "예산 대비 실적 차이 검토",
            ],
        },
        "RF-002": {
            "risk_family": "Cash Flow",
            "triggered_title": "영업이익 감소와 영업현금흐름 증가의 불일치",
            "monitoring_title": "영업이익과 영업현금흐름의 질적 구성 확인",
            "triggered_interpretation": (
                "영업이익과 영업현금흐름이 반대 방향으로 움직였습니다. "
                "운전자본, 비현금항목 및 일회성 현금흐름의 영향을 "
                "구분할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "영업이익 감소와 현금흐름 증가가 동시에 발생하는 "
                "기준에는 해당하지 않았습니다. 다만 현금흐름 개선이 "
                "본원적 영업성과에서 발생했는지는 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "매출채권 회수 개선",
                "재고 축소",
                "매입채무 결제시점 변화",
                "감가상각비 등 비현금비용 증가",
            ],
            "audit_risks": [
                "운전자본 계정의 기간귀속 오류",
                "현금흐름표 분류 오류",
                "비경상 현금유입의 영업활동 분류",
            ],
            "assertions": ["완전성", "기간귀속", "분류", "정확성"],
            "triggered_questions": [
                "이익 감소에도 영업현금흐름이 증가한 가장 큰 조정항목은 무엇입니까?",
                "운전자본 개선 중 일시적 결제시점 효과가 포함되어 있습니까?",
            ],
            "monitoring_questions": [
                "영업현금흐름 증감에 가장 크게 기여한 운전자본 항목은 무엇입니까?",
                "비현금항목과 일회성 항목을 제외한 현금창출력은 어떻게 변했습니까?",
            ],
            "documents": [
                "영업현금흐름 조정내역",
                "운전자본 증감표",
                "비현금항목 명세",
                "현금흐름표 작성 근거",
            ],
            "procedures": [
                "현금흐름표 재계산",
                "주요 운전자본 계정 증감 검토",
                "현금흐름 분류 적정성 테스트",
            ],
        },
        "RF-003": {
            "risk_family": "Impairment",
            "triggered_title": "높은 영업권 비중과 수익성 저하",
            "monitoring_title": "영업권 비중과 손상검사 가정 모니터링",
            "triggered_interpretation": (
                "영업권 비중이 높고 수익성이 악화되어 현금창출단위의 "
                "회수가능액과 손상검사 가정에 대한 검토 중요성이 높습니다."
            ),
            "monitoring_interpretation": (
                "높은 영업권 비중과 수익성 저하가 동시에 발생하는 "
                "기준에는 해당하지 않았습니다. 다만 영업권은 추정과 "
                "판단이 큰 항목이므로 주요 가정을 정기적으로 확인해야 합니다."
            ),
            "normal_causes": [
                "인수 이후 계획된 통합비용",
                "시장 확대를 위한 선투자",
                "현금창출단위의 장기 성장 단계",
            ],
            "audit_risks": [
                "손상차손 미인식",
                "현금흐름 예측의 과도한 낙관성",
                "할인율 또는 영구성장률의 편향",
            ],
            "assertions": ["평가", "정확성", "표시"],
            "triggered_questions": [
                "수익성 저하를 손상검사 현금흐름 추정에 어떻게 반영했습니까?",
                "할인율과 영구성장률의 변경 근거는 무엇입니까?",
            ],
            "monitoring_questions": [
                "영업권이 배분된 현금창출단위의 최근 실적은 사업계획과 일치합니까?",
                "손상검사 핵심 가정의 민감도는 어느 수준입니까?",
            ],
            "documents": [
                "영업권 배분표",
                "손상검사 보고서",
                "현금흐름 예측 및 사업계획",
                "할인율과 영구성장률 산정자료",
            ],
            "procedures": [
                "사업계획과 과거 예측 정확도 비교",
                "할인율 및 성장률 독립 검토",
                "민감도 분석 재수행",
            ],
        },
        "RF-004": {
            "risk_family": "Receivables",
            "triggered_title": "매출 성장률을 유의하게 상회하는 매출채권 증가",
            "monitoring_title": "매출 증가율 대비 매출채권 증가 모니터링",
            "triggered_interpretation": (
                "매출채권 증가율이 매출 증가율보다 10%p 이상 높습니다. "
                "회수기간 장기화, 매출의 기간귀속 및 대손충당금 평가를 "
                "중점적으로 확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "매출채권 증가율이 매출 증가율을 10%p 이상 초과하는 "
                "기준에는 미달했습니다. 다만 증가 격차가 존재하는 경우 "
                "고객별 회수조건과 연체 구성을 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "연말 매출 집중",
                "신규 대형 고객의 결제조건",
                "해외매출 비중 확대",
                "매출채권 양도 또는 회수 일정 변화",
            ],
            "audit_risks": [
                "매출 조기인식",
                "매출채권 회수가능성 저하",
                "대손충당금 과소계상",
                "특수관계자 거래 미식별",
            ],
            "assertions": ["발생", "기간귀속", "평가", "권리와 의무"],
            "triggered_questions": [
                "매출채권 증가가 특정 고객, 지역 또는 제품에 집중되어 있습니까?",
                "평균 회수기간과 연체율은 전년 대비 어떻게 변했습니까?",
            ],
            "monitoring_questions": [
                "매출채권 증가율이 매출 증가율보다 높은 주요 원인은 무엇입니까?",
                "보고기간 후 회수 실적과 연체채권 구성에 유의한 변화가 있습니까?",
            ],
            "documents": [
                "매출채권 연령분석표",
                "보고기간 후 입금내역",
                "주요 고객별 잔액 및 거래조건",
                "대손충당금 산정자료",
            ],
            "procedures": [
                "외부조회",
                "보고기간 후 입금 테스트",
                "매출 기간귀속 테스트",
                "대손충당금 재계산",
            ],
        },
        "RF-005": {
            "risk_family": "Inventory",
            "triggered_title": "매출 성장률을 유의하게 상회하는 재고 증가",
            "monitoring_title": "매출 증가율 대비 재고자산 변화 모니터링",
            "triggered_interpretation": (
                "재고 증가율이 매출 증가율보다 10%p 이상 높습니다. "
                "수요 둔화, 장기체화 및 순실현가능가치 하락 위험을 "
                "확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "재고 증가율이 매출 증가율을 10%p 이상 초과하는 "
                "기준에는 해당하지 않았습니다. 재고 회전과 평가충당금 "
                "추세는 계속 모니터링할 필요가 있습니다."
            ),
            "normal_causes": [
                "신제품 출시 준비",
                "공급망 안정화를 위한 안전재고 확보",
                "계절적 수요 대응",
                "원재료 가격 상승에 대비한 선구매",
            ],
            "audit_risks": [
                "장기체화 재고 미식별",
                "순실현가능가치 평가 오류",
                "재고 수량 또는 소유권 오류",
                "원가 배부 오류",
            ],
            "assertions": ["존재", "평가", "권리와 의무", "완전성"],
            "triggered_questions": [
                "재고 증가가 어떤 품목과 사업부에 집중되어 있습니까?",
                "장기체화 및 순실현가능가치 하락 징후를 어떻게 평가했습니까?",
            ],
            "monitoring_questions": [
                "재고 회전일수와 장기체화 재고 비중은 전년 대비 어떻게 변했습니까?",
                "평가충당금 산정에 사용한 판매가격과 처분비용 가정은 무엇입니까?",
            ],
            "documents": [
                "재고 연령분석표",
                "품목별 판매실적",
                "순실현가능가치 평가자료",
                "재고평가충당금 산정표",
            ],
            "procedures": [
                "재고실사 입회",
                "장기체화 재고 테스트",
                "순실현가능가치 재계산",
                "매입 및 제조원가 테스트",
            ],
        },
        "RF-006": {
            "risk_family": "Earnings Quality",
            "triggered_title": "영업이익 흑자와 대규모 순손실의 괴리",
            "monitoring_title": "영업이익과 당기순손익의 구성 모니터링",
            "triggered_interpretation": (
                "영업이익은 흑자이나 당기순손실 규모가 더 큽니다. "
                "금융손익, 지분법손익, 손상차손 및 일회성 항목의 "
                "완전성과 평가를 확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "영업이익 흑자와 대규모 순손실이 동시에 발생하는 "
                "기준에는 해당하지 않았습니다. 영업외손익과 세금효과가 "
                "당기순손익에 미친 영향은 계속 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "환율 및 금리 변동",
                "일회성 자산 처분손익",
                "지분법손익 변동",
                "법인세 비용 변동",
            ],
            "audit_risks": [
                "손상차손 또는 충당부채 누락",
                "금융상품 평가 오류",
                "비경상항목의 부적절한 분류",
            ],
            "assertions": ["완전성", "평가", "분류", "정확성"],
            "triggered_questions": [
                "대규모 순손실을 발생시킨 비영업 항목의 세부 구성은 무엇입니까?",
                "해당 손실 항목이 다음 연도에도 반복될 가능성이 있습니까?",
            ],
            "monitoring_questions": [
                "영업이익과 당기순손익 차이를 구성하는 주요 항목은 무엇입니까?",
                "영업외손익 중 추정과 평가가 큰 항목은 무엇입니까?",
            ],
            "documents": [
                "금융손익 명세",
                "지분법손익 명세",
                "손상차손 및 충당부채 자료",
                "비경상항목 분석표",
            ],
            "procedures": [
                "주요 영업외손익 증빙 검사",
                "금융상품 평가 재계산",
                "손상 및 충당부채 완전성 검토",
            ],
        },
        "RF-007": {
            "risk_family": "Investments",
            "triggered_title": "관계기업투자 감소와 순손실 동시 발생",
            "monitoring_title": "관계기업투자 변동과 지분법손익 모니터링",
            "triggered_interpretation": (
                "관계기업투자가 감소하고 당기순손실이 발생했습니다. "
                "처분, 지분법손실 또는 손상차손의 적정성을 확인할 "
                "필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "관계기업투자 감소와 순손실이 동시에 발생하는 기준에는 "
                "해당하지 않았습니다. 관계기업별 장부금액 변동과 "
                "손상징후는 별도로 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "관계기업 지분 취득 또는 처분",
                "배당금 수령",
                "지분법이익 또는 손실",
                "환율 변동",
            ],
            "audit_risks": [
                "지분법손익 계산 오류",
                "손상징후 미식별",
                "처분손익 또는 취득원가 오류",
            ],
            "assertions": ["평가", "권리와 의무", "정확성", "표시"],
            "triggered_questions": [
                "관계기업투자 감소가 처분, 지분법손실, 손상 중 어디에서 발생했습니까?",
                "관계기업의 재무상태 악화나 손상징후를 어떻게 평가했습니까?",
            ],
            "monitoring_questions": [
                "관계기업별 장부금액 변동의 주요 원인은 무엇입니까?",
                "손상징후 검토에 사용한 재무·비재무 지표는 무엇입니까?",
            ],
            "documents": [
                "관계기업별 장부금액 변동표",
                "지분법 계산자료",
                "손상검토 자료",
                "취득 및 처분 계약서",
            ],
            "procedures": [
                "지분법 계산 재수행",
                "관계기업 재무정보 검토",
                "손상징후 및 회수가능액 평가",
            ],
        },
        "RF-008": {
            "risk_family": "Profitability",
            "triggered_title": "2년 연속 영업이익률 하락",
            "monitoring_title": "3개년 영업이익률 추세 모니터링",
            "triggered_interpretation": (
                "영업이익률이 2년 연속 하락했습니다. 원가구조 변화와 "
                "손익 추정의 편향, 자산 손상징후를 함께 검토할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "영업이익률이 2년 연속 하락하는 기준에는 해당하지 "
                "않았습니다. 최근 수익성 개선 또는 변동의 지속 가능성과 "
                "일회성 효과 여부를 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "제품믹스 개선 또는 악화",
                "원가 절감 효과",
                "가격정책 변화",
                "일회성 비용 또는 환입",
            ],
            "audit_risks": [
                "비용 인식 시점 조정",
                "충당부채 또는 손상차손 누락",
                "부문별 성과 측정 오류",
            ],
            "assertions": ["완전성", "기간귀속", "평가", "분류"],
            "triggered_questions": [
                "영업이익률이 2년 연속 하락한 주요 사업적 원인은 무엇입니까?",
                "수익성 회복 계획의 핵심 가정과 실현 가능성은 무엇입니까?",
            ],
            "monitoring_questions": [
                "3개년 영업이익률 변화의 핵심 원인은 무엇입니까?",
                "최근 개선이 가격, 믹스, 원가절감 또는 일회성 효과 중 어디에서 발생했습니까?",
            ],
            "documents": [
                "연도별 예산 대비 실적",
                "부문별 마진 분석",
                "주요 원가 및 비용 증감자료",
                "향후 사업계획",
            ],
            "procedures": [
                "부문별 이익률 추세 분석",
                "예산과 실제 실적 비교",
                "수익성 관련 추정치 검토",
            ],
        },
        "RF-009": {
            "risk_family": "Loss Trend",
            "triggered_title": "매출 성장에도 2개년 연속 순손실",
            "monitoring_title": "매출 성장과 순손익 추세 모니터링",
            "triggered_interpretation": (
                "매출이 성장했지만 2개년 연속 순손실이 발생했습니다. "
                "손실의 반복 가능성과 계속기업, 자산 손상 및 충당부채 "
                "위험을 확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "매출 성장과 2개년 연속 순손실이 동시에 발생하는 "
                "기준에는 해당하지 않았습니다. 매출 성장의 수익 기여도와 "
                "비경상 손익의 영향을 확인할 필요가 있습니다."
            ),
            "normal_causes": [
                "신규 사업 초기 투자",
                "일회성 구조조정 비용",
                "금융비용 또는 환율 변동",
                "법인세 비용 변동",
            ],
            "audit_risks": [
                "계속기업 불확실성",
                "손상차손 및 충당부채 누락",
                "매출의 조기인식",
            ],
            "assertions": ["발생", "완전성", "평가", "표시"],
            "triggered_questions": [
                "매출 성장에도 순손실이 지속된 핵심 원인은 무엇입니까?",
                "손실이 반복될 가능성과 자금조달 계획을 어떻게 평가하고 있습니까?",
            ],
            "monitoring_questions": [
                "매출 성장분이 영업이익과 순이익으로 연결된 정도는 어떠합니까?",
                "당기순손익에 유의한 영향을 미친 비경상항목은 무엇입니까?",
            ],
            "documents": [
                "손실 원인 분석표",
                "비경상항목 명세",
                "향후 손익 및 현금흐름 전망",
                "자금조달 계획",
            ],
            "procedures": [
                "계속기업 평가 검토",
                "비경상항목 증빙 검사",
                "손상 및 충당부채 완전성 검토",
            ],
        },
        "RF-010": {
            "risk_family": "Asset Efficiency",
            "triggered_title": "자산회전율 개선에도 음의 ROA",
            "monitoring_title": "자산회전율과 ROA의 관계 모니터링",
            "triggered_interpretation": (
                "자산 활용도는 개선됐으나 ROA가 음수입니다. "
                "영업외손실, 자산 손상 및 비수익 자산의 평가를 "
                "확인할 필요가 있습니다."
            ),
            "monitoring_interpretation": (
                "자산회전율 개선과 음의 ROA가 동시에 발생하는 기준에는 "
                "해당하지 않았습니다. 자산 활용도와 수익성 변화의 원인은 "
                "계속 모니터링할 필요가 있습니다."
            ),
            "normal_causes": [
                "대규모 신규 투자 이후 정상화 과정",
                "저수익 자산 보유",
                "일회성 영업외손실",
                "사업 포트폴리오 변화",
            ],
            "audit_risks": [
                "자산 손상차손 미인식",
                "비수익 자산의 과대계상",
                "영업외손익 분류 오류",
            ],
            "assertions": ["평가", "존재", "분류", "정확성"],
            "triggered_questions": [
                "자산회전율 개선에도 ROA가 음수인 주요 원인은 무엇입니까?",
                "저수익 또는 비수익 자산에 대한 손상검토를 수행했습니까?",
            ],
            "monitoring_questions": [
                "자산회전율과 ROA 변화에 가장 크게 기여한 사업부 또는 자산은 무엇입니까?",
                "신규 투자자산의 계획 대비 수익 실적은 어떠합니까?",
            ],
            "documents": [
                "자산별 수익성 분석",
                "손상검사 자료",
                "영업외손익 명세",
                "신규 투자 사후평가 자료",
            ],
            "procedures": [
                "자산별 수익성 분석",
                "손상징후 검토",
                "주요 투자자산의 실적과 사업계획 비교",
            ],
        },
    }

    # -----------------------------------------------------
    # 우선순위 점수
    # 발동 시 100점 이상, 미발동은 수치 근접도와 감사 중요도 반영
    # -----------------------------------------------------
    monitoring_scores = {
        "RF-001": (
            45
            + max(
                0,
                -metrics["operating_margin_change_2025_ppt"]
            ) * 5
        ),
        "RF-002": (
            48
            if (
                (op["2025"] - op["2024"])
                * (ocf["2025"] - ocf["2024"]) < 0
            )
            else 38
        ),
        "RF-003": (
            35
            + min(
                30,
                metrics["goodwill_to_assets_2025_pct"]
            )
        ),
        "RF-004": (
            55
            + max(
                0,
                metrics["receivables_vs_revenue_gap_pct"]
            ) * 2
        ),
        "RF-005": (
            48
            + max(
                0,
                metrics["inventory_vs_revenue_gap_pct"]
            ) * 2
        ),
        "RF-006": (
            50
            if net["2025"] >= 0
            else 75
        ),
        "RF-007": (
            45
            if associates["2025"] >= associates["2024"]
            else 65
        ),
        "RF-008": (
            52
            + max(
                0,
                metrics["operating_margin_2024_pct"]
                - metrics["operating_margin_2025_pct"]
            ) * 4
        ),
        "RF-009": (
            48
            + (15 if net["2025"] < 0 else 0)
            + (15 if net["2024"] < 0 else 0)
        ),
        "RF-010": (
            45
            + (25 if metrics["roa_2025_pct"] < 0 else 0)
        ),
    }

    flags = []

    for flag_id in [
        "RF-001",
        "RF-002",
        "RF-003",
        "RF-004",
        "RF-005",
        "RF-006",
        "RF-007",
        "RF-008",
        "RF-009",
        "RF-010",
    ]:
        detail = rule_details[flag_id]
        triggered = bool(conditions[flag_id])

        title = (
            detail["triggered_title"]
            if triggered
            else detail["monitoring_title"]
        )

        interpretation = (
            detail["triggered_interpretation"]
            if triggered
            else detail["monitoring_interpretation"]
        )

        questions = (
            detail["triggered_questions"]
            if triggered
            else detail["monitoring_questions"]
        )

        priority_score = (
            100 + monitoring_scores[flag_id]
            if triggered
            else monitoring_scores[flag_id]
        )

        flag = {
            "flag_id": flag_id,
            "risk_family": detail["risk_family"],
            "title": title,
            "triggered": triggered,
            "status": (
                "Red Flag"
                if triggered
                else "Monitoring Signal"
            ),
            "priority_score": round(
                float(priority_score),
                1,
            ),
            "observed_fact": evidence[flag_id],
            "evidence": evidence[flag_id],
            "interpretation": interpretation,
            "possible_normal_causes": (
                detail["normal_causes"]
            ),
            "possible_audit_risks": (
                detail["audit_risks"]
            ),
            "assertions": detail["assertions"],
            "interview_questions": questions,
            "interview_question": questions[0],
            "evidence_requests": (
                detail["documents"]
            ),
            "evidence_request": ", ".join(
                detail["documents"]
            ),
            "follow_up_procedures": (
                detail["procedures"]
            ),
            "disclaimer": DISCLAIMER,
        }

        flags.append(flag)

    return flags, metrics




def select_top_3(flags: list) -> list:
    """
    Red Flag를 우선 배치하고, 부족한 자리는
    priority_score가 높은 Monitoring Signal로 채운다.

    가능하면 서로 다른 위험군을 우선 선택한다.
    """
    ordered = sorted(
        flags,
        key=lambda flag: (
            not flag["triggered"],
            -float(flag.get("priority_score", 0)),
        ),
    )

    selected = []
    used_families = set()

    # 1차: 위험군 중복 없이 선택
    for flag in ordered:
        family = flag.get("risk_family")

        if family in used_families:
            continue

        selected.append(flag)
        used_families.add(family)

        if len(selected) == 3:
            return selected

    # 2차: 위험군이 겹치더라도 3개 채우기
    selected_ids = {
        flag.get("flag_id")
        for flag in selected
    }

    for flag in ordered:
        if flag.get("flag_id") in selected_ids:
            continue

        selected.append(flag)

        if len(selected) == 3:
            break

    return selected




def save_results(
    company: str,
    source_file: str,
    validation: dict,
    flags: list,
    metrics: dict,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    red_flags = [
        flag
        for flag in flags
        if flag["triggered"]
    ]

    monitoring = [
        flag
        for flag in flags
        if not flag["triggered"]
    ]

    top_3 = select_top_3(flags)

    result = {
        "company": company,
        "source_file": source_file,
        "analysis_period": "2023-2025",
        "validation": validation,
        "metrics": metrics,
        "rule_count": len(flags),
        "red_flag_count": len(red_flags),
        "monitoring_signal_count": len(monitoring),
        "top_3": top_3,
        "red_flags": red_flags,
        "monitoring_signals": monitoring,
        "all_results": flags,
        "disclaimer": DISCLAIMER,
    }

    json_path = (
        output_dir
        / "runtime_audit_analysis.json"
    )

    with json_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    lines = [
        f"# {company} Audit Red Flag Report",
        "",
        f"- 입력파일: {source_file}",
        "- 분석기간: 2023-2025",
        f"- 전체 규칙: {len(flags)}개",
        f"- Red Flag: {len(red_flags)}개",
        f"- Monitoring Signal: {len(monitoring)}개",
        "",
        "## Top 3 우선 검토 영역",
        "",
    ]

    for index, flag in enumerate(
        top_3,
        start=1,
    ):
        lines.extend([
            f"### {index}. {flag['title']}",
            "",
            f"- 구분: {flag['status']}",
            f"- 위험군: {flag['risk_family']}",
            f"- 우선순위 점수: {flag['priority_score']}",
            f"- 관측 사실: {flag['observed_fact']}",
            f"- 감사상 의미: {flag['interpretation']}",
            (
                "- 관련 주장: "
                + ", ".join(flag["assertions"])
            ),
            "",
            "#### 경영진 인터뷰 질문",
            "",
        ])

        for question in flag[
            "interview_questions"
        ]:
            lines.append(f"- {question}")

        lines.extend([
            "",
            "#### 요청자료",
            "",
        ])

        for document in flag[
            "evidence_requests"
        ]:
            lines.append(f"- {document}")

        lines.extend([
            "",
            "#### 가능한 정상적 원인",
            "",
        ])

        for cause in flag[
            "possible_normal_causes"
        ]:
            lines.append(f"- {cause}")

        lines.extend([
            "",
            "#### 잠재 회계·감사 위험",
            "",
        ])

        for risk in flag[
            "possible_audit_risks"
        ]:
            lines.append(f"- {risk}")

        lines.extend([
            "",
            "#### 후속 감사절차",
            "",
        ])

        for procedure in flag[
            "follow_up_procedures"
        ]:
            lines.append(f"- {procedure}")

        lines.extend([
            "",
            "---",
            "",
        ])

    lines.extend([
        "## 추가 모니터링 포인트",
        "",
    ])

    top_ids = {
        flag["flag_id"]
        for flag in top_3
    }

    remaining_monitoring = sorted(
        [
            flag
            for flag in monitoring
            if flag["flag_id"] not in top_ids
        ],
        key=lambda flag: -float(
            flag.get("priority_score", 0)
        ),
    )

    for flag in remaining_monitoring:
        lines.extend([
            f"### {flag['title']}",
            "",
            f"- 위험군: {flag['risk_family']}",
            f"- 관측 사실: {flag['observed_fact']}",
            f"- 해석: {flag['interpretation']}",
            "",
        ])

    lines.extend([
        "## 주의사항",
        "",
        DISCLAIMER,
        "",
    ])

    markdown_path = (
        output_dir
        / "runtime_audit_report.md"
    )

    with markdown_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n".join(lines))

    return json_path, markdown_path



def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "표준 CSV 재무데이터를 분석해 감사 Red Flag와 "
            "인터뷰 질문을 생성합니다."
        )
    )

    parser.add_argument(
        "input_csv",
        help="분석할 CSV 파일 경로",
    )

    parser.add_argument(
        "--company",
        default=None,
        help="기업명. 생략하면 CSV의 company 열 또는 파일명을 사용합니다.",
    )

    parser.add_argument(
        "--output-dir",
        default="runtime_outputs",
        help="결과 저장 폴더",
    )

    args = parser.parse_args()

    input_path = Path(args.input_csv)

    if not input_path.exists():
        raise FileNotFoundError(
            f"입력 파일을 찾을 수 없습니다: {input_path}"
        )

    original_data = pd.read_csv(
        input_path,
        encoding="utf-8-sig",
    )

    if args.company:
        company = args.company
    elif (
        "company" in original_data.columns
        and not original_data["company"].dropna().empty
    ):
        company = str(
            original_data["company"].dropna().iloc[0]
        )
    else:
        company = input_path.stem

    analysis_data, validation = load_and_validate(input_path)
    flags, metrics = run_rules(analysis_data)

    json_path, markdown_path = save_results(
        company=company,
        source_file=input_path.name,
        validation=validation,
        flags=flags,
        metrics=metrics,
        output_dir=Path(args.output_dir),
    )

    red_flag_count = sum(
        flag["triggered"] for flag in flags
    )

    print("분석 완료")
    print("기업:", company)
    print("Red Flag:", red_flag_count)
    print("Monitoring Signal:", len(flags) - red_flag_count)
    print("JSON:", json_path)
    print("보고서:", markdown_path)


if __name__ == "__main__":
    main()
