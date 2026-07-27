from sensor_to_shooter import cli


def test_cli_prints_events(synthetic_sicd, capsys):
    rc = cli.main([synthetic_sicd, "--threshold-sigma", "5.0"])
    assert rc == 0
    out = capsys.readouterr()
    assert "<event" in out.out
    assert "a-h-G" in out.out
    assert "u-d-f" in out.out
    assert "detections=" in out.err


def test_cli_no_detect_footprint_only(synthetic_sicd, capsys):
    rc = cli.main([synthetic_sicd, "--no-detect"])
    assert rc == 0
    out = capsys.readouterr()
    assert "u-d-f" in out.out
    assert "a-h-G" not in out.out
