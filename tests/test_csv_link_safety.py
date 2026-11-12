"""CSV-provided problem links are rebuilt from the validated slug only - a
crafted sheet can never plant a javascript: or lookalike-host href."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.leetcode_sheet import parse_user_csv  # noqa: E402


def test_javascript_link_neutralized():
    rows = parse_user_csv(
        "Difficulty,Title,Frequency,Acceptance Rate,Link,Topics\n"
        'EASY,Two Sum,100.0,0.5,https://leetcode.com/problems/two-sum/,"Arrays"\n'
        'EASY,Evil,100.0,0.5,javascript:alert(1),"Arrays"\n')
    assert [r["title"] for r in rows] == ["Two Sum"]  # slug-less crafted row dropped
    assert all(not r["link"].startswith("javascript:") for r in rows)


def test_lookalike_host_canonicalized():
    rows = parse_user_csv(
        "Difficulty,Title,Frequency,Acceptance Rate,Link,Topics\n"
        'EASY,Two Sum,100.0,0.5,https://leetcode.com.evil.example/problems/two-sum/,"Arrays"\n')
    assert rows[0]["link"] == "https://leetcode.com/problems/two-sum/"


def test_legit_link_canonicalized():
    rows = parse_user_csv(
        "problem_link,problem_name,num_occur\n"
        "https://leetcode.com/problems/add-two-numbers/,Add Two Numbers,9\n")
    assert rows[0]["link"] == "https://leetcode.com/problems/add-two-numbers/"
