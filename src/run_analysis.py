from pathlib import Path
import json
import pandas as pd


DISCLAIMER = (
    "식별된 Red Flag는 오류나 부정의 존재를 의미하는 것이 아니라, "
    "기업 및 환경에 대한 이해와 중요왜곡표시위험 평가를 위해 "
    "추가적인 질문과 검토가 필요한 영역을 의미한다."
)


def get_account_values(
    data: pd.DataFrame,
    account_name: str
) -> pd.Series:
    result = data.loc[
        data["account"] == account_name,
        ["2023", "2024", "2025"]
    ]

    if len(result) != 1:
        raise ValueError(
            f"{account_name} 계정은 정확히 한 행이어야 합니다."
        )

    values = result.iloc[0].apply(
        pd.to_numeric,
        errors="coerce"
    )

    if values.isna().any():
        raise ValueError(
            f"{account_name} 계정에 누락되거나 잘못된 숫자가 있습니다."
        )

    return values.astype(float)


def analyze_profitability_gap(
    data: pd.DataFrame
) -> dict:
    revenue = get_account_values(
        data,
        "Revenue"
    )

    operating_profit = get_account_values(
        data,
        "Operating_Profit"
    )

    revenue_growth_2025 = (
        revenue["2025"] / revenue["2024"] - 1
    ) * 100

    operating_margin_2024 = (
        operating_profit["2024"]
        / revenue["2024"]
        * 100
    )

    operating_margin_2025 = (
        operating_profit["2025"]
        / revenue["2025"]
        * 100
    )

    margin_change = (
        operating_margin_2025
        - operating_margin_2024
    )

    triggered = bool(
        revenue_growth_2025 > 0
        and margin_change <= -3
    )

    return {
        "flag_id": "RF-001",
        "title": "외형 성장과 수익성 악화의 괴리",
        "confirmed_facts": {
            "2025_revenue_growth_pct": round(
                float(revenue_growth_2025),
                1
            ),
            "2024_operating_margin_pct": round(
                float(operating_margin_2024),
                1
            ),
            "2025_operating_margin_pct": round(
                float(operating_margin_2025),
                1
            ),
            "margin_change_ppt": round(
                float(margin_change),
                1
            )
        },
        "rule": (
            "매출이 증가했지만 영업이익률이 "
            "전년 대비 3%p 이상 하락"
        ),
        "rule_triggered": triggered,
        "status": (
            "추가 검토 필요"
            if triggered
            else "추세 모니터링"
        ),
        "disclaimer": DISCLAIMER
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]

    input_path = (
        project_root
        / "samples"
        / "sample_financial_input.csv"
    )

    output_path = (
        project_root
        / "samples"
        / "sample_runtime_output.json"
    )

    data = pd.read_csv(input_path)

    result = analyze_profitability_gap(data)

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    print("분석 완료")
    print("규칙 충족 여부:", result["rule_triggered"])
    print("결과 파일:", output_path)


if __name__ == "__main__":
    main()
