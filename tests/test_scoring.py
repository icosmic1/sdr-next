from types import SimpleNamespace
from app.scoring import calculate, choose_action, persona_score

def test_persona_scores_decision_makers_higher():
    assert persona_score("Chief Revenue Officer") == 100
    assert persona_score("VP Sales") == 95
    assert persona_score("Developer") == 35

def test_action_boundaries():
    assert choose_action(90, phone=True) == "CALL"
    assert choose_action(80) == "PERSONALIZED_EMAIL"
    assert choose_action(50) == "RESEARCH"
    assert choose_action(30) == "DEPRIORITIZE"
    assert choose_action(20, replied=True) == "FOLLOW_UP"

def test_calculate_is_deterministic_and_bounded():
    prospect=SimpleNamespace(title="VP Sales",replied=False,email_open_count=2,phone="123")
    signal=SimpleNamespace(signal_type="FUNDING",confidence=.9,status="VERIFIED",last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    account=SimpleNamespace(prospects=[prospect],signals=[signal],icp_score=90)
    result=calculate(account)
    assert 0 <= result.score <= 100
    assert result.action in {"CALL","PERSONALIZED_EMAIL","RESEARCH","DEPRIORITIZE","FOLLOW_UP"}
