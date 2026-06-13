def test_package_imports():
    import ema_poc

    assert ema_poc.__name__ == "ema_poc"
    assert ema_poc.__version__ == "0.1.0"
