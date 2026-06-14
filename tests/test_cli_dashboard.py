from ema_poc.cli import Deps, main


class _Config:
    class settings:
        db_path = "ema.sqlite"

    class brands:
        abbvie_brands = ["Skyrizi", "Rinvoq"]
        competitor_brands = ["Humira"]


def test_dashboard_command_invokes_build_and_reports(tmp_path):
    calls = {}
    out = []

    def _build(conn, out_path, *, abbvie_brands, competitor_brands, now=""):
        calls["out_path"] = out_path
        calls["abbvie_brands"] = abbvie_brands
        calls["competitor_brands"] = competitor_brands
        return out_path

    deps = Deps(
        load_config=lambda d: _Config(),
        connect=lambda p: "CONN",
        init_schema=lambda c: None,
        validate_credentials=lambda config, env: (_ for _ in ()).throw(
            AssertionError("dashboard must not validate credentials")),
        build_adapters=lambda config, env: [],
        make_scoring_client=lambda env: None,
        run=lambda *a, **k: None,
        score_pending=lambda *a, **k: None,
        check_targets=lambda adapters: [],
        import_csv=lambda c, p: 0,
        import_excel=lambda c, p: 0,
        env={},
        out=out.append,
        build_dashboard=_build,
    )
    rc = main(["dashboard", "--out", str(tmp_path / "d.html")], deps=deps)
    assert rc == 0
    assert calls["out_path"] == str(tmp_path / "d.html")
    assert calls["abbvie_brands"] == ["Skyrizi", "Rinvoq"]
    assert calls["competitor_brands"] == ["Humira"]
    assert any("Dashboard written" in line for line in out)
