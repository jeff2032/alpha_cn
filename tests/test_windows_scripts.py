from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_nightly_prep_omits_empty_final_stock_provider() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_nightly_research_prep.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert 'if ($FinalStockProvider) {' in script
    assert '$dataSyncParameters["FinalStockProvider"] = $FinalStockProvider' in script
    assert 'FinalStockProvider = $FinalStockProvider' not in script


def test_nightly_prep_avoids_nested_powershell_transcript() -> None:
    nightly = (PROJECT_ROOT / "scripts" / "run_nightly_research_prep.ps1").read_text(
        encoding="utf-8-sig"
    )
    sync = (PROJECT_ROOT / "scripts" / "run_data_sync.ps1").read_text(encoding="utf-8-sig")

    assert '& $ScriptPath @Parameters' in nightly
    assert 'DisableTranscript = $true' in nightly
    assert '[switch]$DisableTranscript' in sync
    assert 'if (-not $DisableTranscript)' in sync
    assert 'Start-Transcript -Path $script:LogPath -Append' not in nightly
    assert 'Start-Transcript -Path $logPath -Append' not in sync


def test_weekend_skip_does_not_overwrite_current_status() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_nightly_research_prep.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert 'Save-PrepReport -Status "跳过" -Detail "周末默认不跑。" -CheckpointOnly' in script


def test_data_sync_uses_bounded_provider_concurrency() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_data_sync.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert '$Provider -eq "sina" -and $effective -gt 3' in script
    assert 'clamp Workers from $effective to 3' in script
    assert '$Provider -eq "sina" -and $SymbolCount -le 100' in script
    assert 'clamp Workers from $effective to 1' in script
    assert '$Provider -eq "tencent" -and $effective -gt 4' in script


def test_nightly_prep_accepts_high_coverage_and_skips_repeat_universe_refresh() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_nightly_research_prep.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert '[double]$MinCoveragePct = 99.0' in script
    assert 'Get-CoveragePercentage' in script
    assert '-or $coverageReady' in script
    assert 'SkipUniverseRefresh = ($attempt -gt 1)' in script
    assert 'Invoke-QuantStep -Name "数据覆盖预检"' in script
    assert '跳过重复下载' in script
    assert 'Invoke-QuantStep -Name "官方交易日历解析"' in script
    assert 'Invoke-QuantStep -Name "审计并隔离异常日线缓存"' in script
    assert 'Invoke-QuantStep -Name "单一数据源全量修复隔离缓存"' in script
    assert '"--replace-cache"' in script


def test_windows_scripts_force_utf8_python_output() -> None:
    nightly = (PROJECT_ROOT / "scripts" / "run_nightly_research_prep.ps1").read_text(
        encoding="utf-8-sig"
    )
    sync = (PROJECT_ROOT / "scripts" / "run_data_sync.ps1").read_text(encoding="utf-8-sig")

    for script in (nightly, sync):
        assert '$env:PYTHONUTF8 = "1"' in script
        assert '$env:PYTHONIOENCODING = "utf-8"' in script


def test_obsidian_hold_tracking_excludes_expired_execution_windows() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_daily_research.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "function Test-WithinPrimaryWindow" in script
    assert "(Test-WithinPrimaryWindow $_.days_since_entry $_.primary_horizon_days)" in script
