"""部署加固红灯用例(需求 2ecf73bb,2026-08-30 部署报告)。

部署发现两个缺陷,本文件锁定修复契约(设计定稿权在实现者,红灯按契约出题):

1. 执行通道 compose 文件组合缺陷:restart-worker 容器内通道固定 argv 只用根
   docker-compose.yml 重建 cognee;生产多文件 compose 组合(根 + prod + 环境专属
   覆盖层)下,覆盖层注入的 cognee 安全加固在重建后丢失。契约:compose 文件列表
   改为可配置设置项 cognee_compose_files(逗号分隔字符串或列表,默认仅根
   docker-compose.yml 保持开源开箱可用),通道按配置逐个追加 ``-f <file>``;
   其余安全契约(无 shell、固定子命令 up -d --force-recreate cognee、timeout、
   check=False、capture_output)在多文件下不回退。
2. runtime env 防泄漏:.scratch/cognee-runtime.env 由 worker 以 root:0600 重写
   并写入解密后的 LLM_API_KEY,却被 git 跟踪。契约:.gitignore 必须含该路径
   (或等价运行时 env 路径配置);``git rm --cached`` 属实现动作,测试只锁
   .gitignore 契约。

所有测试经替身 argv 捕获,绝不调用真实 docker / docker.sock,不触碰真实 git。
"""

import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import cognee_restart_jobs

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ENV_FILE = ".scratch/cognee-runtime.env"

# 多文件组合样例:根文件 + 生产覆盖层 + 环境专属覆盖层(相对 compose 项目目录)。
MULTI_COMPOSE_FILES = (
    "docker-compose.yml",
    "deploy/docker-compose.prod.yml",
    "deploy/docker-compose.dev.yml",
)

_MISSING_SETTING = (
    "缺少可配置 compose 文件列表设置 settings.cognee_compose_files:"
    "restart-worker 容器内通道固定只用根 docker-compose.yml 重建 cognee,"
    "生产多文件 compose 组合(根+prod+环境专属层)的安全加固在重建后丢失;"
    "compose 文件列表必须可配置,默认仅根 docker-compose.yml 保持开源开箱可用"
)


def _parse_compose_files(raw) -> list[str]:
    """契约:接受逗号/空白分隔字符串或序列,归一化为有序文件列表。"""
    if isinstance(raw, str):
        return [part for part in raw.replace(",", " ").split() if part]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    pytest.fail(
        f"cognee_compose_files 必须是逗号分隔字符串或文件列表,实际类型:{type(raw)}"
    )


def _set_compose_files(monkeypatch, settings, files: list[str]) -> None:
    """按字段既有类型注入配置(字符串用逗号拼接,序列用列表),缺失即红灯。"""
    current = getattr(settings, "cognee_compose_files", None)
    if current is None and not hasattr(settings, "cognee_compose_files"):
        pytest.fail(_MISSING_SETTING)
    if isinstance(current, str):
        value = ",".join(files)
    elif isinstance(current, (list, tuple)):
        value = list(files)
    else:  # pragma: no cover - 实现类型未知时按原样注入
        value = files
    monkeypatch.setattr(settings, "cognee_compose_files", value)


def _capture_compose_run(monkeypatch, tmp_path: Path) -> tuple[dict, Path, Path]:
    """替换 subprocess.run 捕获通道 argv,返回 (captured, runtime_env, project_dir)。"""
    runtime_env = tmp_path / ".scratch" / "cognee-runtime.env"
    project_dir = tmp_path / "compose-project"
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return captured, runtime_env, project_dir


def _compose_file_entries(argv) -> list[str]:
    """按 argv 顺序收集 ``-f`` 后紧跟的 compose 文件路径。"""
    entries: list[str] = []
    for index, token in enumerate(argv):
        if token == "-f":
            assert index + 1 < len(argv), "-f 后必须紧跟 compose 文件路径"
            entries.append(argv[index + 1])
    return entries


def _assert_safe_channel_contract(argv, kwargs, settings, runtime_env: Path, project_dir: Path) -> None:
    """与既有最小权限通道契约一致的安全断言(多文件组合下不得回退)。"""
    assert argv[0] == settings.cognee_compose_executable, "执行器必须来自服务端配置"
    assert "compose" in argv[:2], "必须走 docker compose 子命令"
    assert argv[-1] == "cognee", "重建目标必须是固定的 cognee 服务"
    assert argv.count("cognee") == 1, "不允许出现第二个操作目标"
    for token in ("up", "-d", "--force-recreate"):
        assert token in argv, f"必须以 {token} 重建 cognee 容器(环境变量变更需 recreate)"
    assert "--env-file" in argv and str(runtime_env) in argv, "受管 runtime env 必须传入 compose"
    for forbidden_token in ("down", "rm", "kill", "exec", "run", "ps", "logs"):
        assert forbidden_token not in argv, f"执行通道不允许 docker {forbidden_token}"
    assert kwargs.get("cwd") in (project_dir, Path(project_dir)), (
        "cwd 必须是固定的 compose 项目目录"
    )
    assert kwargs.get("timeout") == settings.cognee_restart_timeout_seconds, "必须带超时防卡死"
    assert kwargs.get("check") is False, "由通道检查 returncode 并转成可读错误"
    assert kwargs.get("capture_output") is True, "必须捕获输出用于错误反馈"
    assert not kwargs.get("shell", False), "禁止 shell 插值"


def test_settings_declare_configurable_compose_file_list_with_safe_default():
    """compose 文件列表必须是可配置设置项,默认仅根 docker-compose.yml。"""
    settings = get_settings()
    if not hasattr(settings, "cognee_compose_files"):
        pytest.fail(_MISSING_SETTING)
    parsed = _parse_compose_files(settings.cognee_compose_files)
    assert parsed == ["docker-compose.yml"], (
        f"默认配置必须仅含根 docker-compose.yml(开源开箱可用,不默认引用环境专属覆盖层),"
        f"实际:{parsed}"
    )


def test_channel_appends_each_configured_compose_file_in_order(monkeypatch, tmp_path):
    """多文件配置:通道逐个 ``-f <file>`` 追加,顺序稳定,且位于 up 子命令之前。"""
    settings = get_settings()
    _set_compose_files(monkeypatch, settings, list(MULTI_COMPOSE_FILES))
    captured, runtime_env, project_dir = _capture_compose_run(monkeypatch, tmp_path)

    channel = cognee_restart_jobs.get_docker_channel()
    channel.recreate_cognee(runtime_env_file=runtime_env, project_dir=project_dir)

    argv = captured["argv"]
    entries = _compose_file_entries(argv)
    assert len(entries) == len(MULTI_COMPOSE_FILES), (
        f"每个配置的 compose 文件必须恰好对应一个 -f 追加,期望 {list(MULTI_COMPOSE_FILES)},实际 {entries}"
    )
    for got, want in zip(entries, MULTI_COMPOSE_FILES):
        assert got in {want, str(Path(want))}, (
            f"-f 追加顺序必须与配置顺序一致:期望 {want},实际 {got}(全部:{entries})"
        )
    up_index = argv.index("up")
    for index, token in enumerate(argv):
        if token == "-f":
            assert index < up_index, (
                "-f 是 docker compose 全局参数,必须位于 up 子命令之前"
            )

    _assert_safe_channel_contract(argv, captured["kwargs"], settings, runtime_env, project_dir)


def test_channel_default_configuration_keeps_open_source_out_of_box_argv(monkeypatch, tmp_path):
    """默认配置(仅根文件)下 argv 与既有开源开箱行为兼容:不引入根文件之外的 compose 文件。"""
    settings = get_settings()
    if not hasattr(settings, "cognee_compose_files"):
        pytest.fail(_MISSING_SETTING)
    default_files = _parse_compose_files(settings.cognee_compose_files)
    captured, runtime_env, project_dir = _capture_compose_run(monkeypatch, tmp_path)

    channel = cognee_restart_jobs.get_docker_channel()
    channel.recreate_cognee(runtime_env_file=runtime_env, project_dir=project_dir)

    argv = captured["argv"]
    entries = _compose_file_entries(argv)
    allowed = {form for file in default_files for form in (file, str(Path(file)))}
    assert set(entries) <= allowed, (
        f"默认配置不得引入根 docker-compose.yml 之外的 compose 文件,实际:{entries}"
    )
    assert len(entries) <= len(default_files), (
        f"默认配置下 -f 数量不得超过默认文件列表,实际:{entries}"
    )

    _assert_safe_channel_contract(argv, captured["kwargs"], settings, runtime_env, project_dir)


def test_runtime_env_file_is_gitignored():
    """防泄漏契约:受管 runtime env 含解密后的 LLM_API_KEY,必须被 .gitignore 忽略。"""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), "仓库根缺少 .gitignore"
    patterns = [
        line.split("#", 1)[0].strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
    ]
    covered = [pattern for pattern in patterns if pattern and RUNTIME_ENV_FILE.split("/")[-1] in pattern]
    assert covered, (
        f".gitignore 缺少 {RUNTIME_ENV_FILE}(或等价运行时 env 路径配置):"
        "该文件由 worker 以 root:0600 重写并写入解密后的 LLM_API_KEY,"
        "被 git 跟踪时未来 git add -A 会把密钥提交进仓库"
    )
