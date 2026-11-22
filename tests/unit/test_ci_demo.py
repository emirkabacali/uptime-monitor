def test_deliberately_broken() -> None:
    # Demonstrates that CI blocks a pull request with a failing test.
    assert 1 + 1 == 3
