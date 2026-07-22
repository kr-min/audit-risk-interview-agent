from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
VERIFIED_ROOT = ROOT / 'verified_demo'

COMPANIES = [
    'samsung_electronics',
    'naver',
    'kakao',
    'hybe',
]

REQUIRED_FIELDS = {
    'flag_id',
    'risk_family',
    'title',
    'triggered',
    'status',
    'priority_score',
    'observed_fact',
    'interpretation',
    'possible_normal_causes',
    'possible_audit_risks',
    'assertions',
    'interview_questions',
    'evidence_requests',
    'follow_up_procedures',
}


def test_verified_outputs():
    for slug in COMPANIES:
        json_path = (
            VERIFIED_ROOT
            / slug
            / 'outputs'
            / f'{slug}_audit_analysis.json'
        )

        assert json_path.exists(), json_path

        with json_path.open('r', encoding='utf-8') as file:
            data = json.load(file)

        assert data['rule_count'] == 10
        assert len(data['all_results']) == 10
        assert len(data['top_3']) == 3
        assert data['red_flag_count'] + data['monitoring_signal_count'] == 10

        for item in data['all_results']:
            assert REQUIRED_FIELDS.issubset(item.keys())
            assert item['interview_questions']
            assert item['evidence_requests']
            assert item['possible_normal_causes']
            assert item['possible_audit_risks']
            assert item['follow_up_procedures']
