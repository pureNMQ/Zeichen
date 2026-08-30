"""容器化部署契约:持久重启 worker 与最小权限 docker.sock 通道(红灯用例)。

根因(需求 2ecf73bb,2026-08-24 仓库核验):`cognee_restart_jobs.submit()` 只落
queued 任务,消费侧 worker `app.workers.cognee_restart` 只出现在宿主开发脚本
start-all.ps1;docker-compose.yml(所有部署形态的公共基底)没有任何服务运行它,
也没有挂载 docker.sock,因此容器化部署下重启任务永远停留在 queued、待应用配置
永不生效。

本文件只断言仓库根 `docker-compose.yml`:prod/ip/dev 覆盖文件仅追加 env、资源
限制与源码挂载,compose 卷按挂载 target 合并,不会移除基底文件的挂载。断言使用
轻量缩进解析,不引入 PyYAML 依赖,也不触碰真实 docker。
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
PROD_OVERRIDE_FILE = REPO_ROOT / "deploy" / "docker-compose.prod.yml"

RESTART_WORKER_MODULE = "app.workers.cognee_restart"
DOCKER_SOCK = "/var/run/docker.sock"

_MISSING_WORKER = (
    f"容器化部署缺少消费 cognee_restart 队列的持久 worker:"
    f"docker-compose.yml 中没有任何服务的 command 运行 {RESTART_WORKER_MODULE},"
    "排队任务将永远无人消费"
)


def _service_blocks(compose_path: Path) -> dict[str, str]:
    """按两空格缩进切出 services 下每个服务的文本块(仅用于契约断言)。"""
    services: dict[str, list[str]] = {}
    current: str | None = None
    in_services = False
    for raw in compose_path.read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"services:\s*", raw):
            in_services = True
            current = None
            continue
        if not in_services:
            continue
        if raw and not raw[0].isspace():
            # 回到顶层键(如 volumes:)→ services 段结束
            in_services = False
            continue
        name = re.match(r"  ([A-Za-z0-9_-]+):\s*(?:#.*)?$", raw)
        if name:
            current = name.group(1)
            services[current] = []
            continue
        if current and raw.strip():
            services[current].append(raw)
    return {name: "\n".join(block) for name, block in services.items()}


def _restart_worker_services(services: dict[str, str]) -> set[str]:
    return {
        name
        for name, block in services.items()
        if RESTART_WORKER_MODULE in block
        and re.search(r"^\s+command:", block, re.M)
    }


def test_containerized_deployment_runs_persistent_cognee_restart_worker():
    services = _service_blocks(COMPOSE_FILE)
    assert services, "docker-compose.yml 未解析到任何 service"
    workers = _restart_worker_services(services)
    assert workers, _MISSING_WORKER
    for name in workers:
        block = services[name]
        # 持久 worker:随宿主自启,避免容器重建后再次出现无人消费的队列
        assert re.search(
            r"^\s+restart:\s*(?:unless-stopped|always)\s*(?:#.*)?$", block, re.M
        ), f"重启 worker 服务 {name} 必须配置 restart: unless-stopped/always"


def test_docker_socket_channel_is_granted_only_to_restart_worker_readonly():
    services = _service_blocks(COMPOSE_FILE)
    workers = _restart_worker_services(services)
    assert workers, _MISSING_WORKER

    sock_services = {name for name, block in services.items() if DOCKER_SOCK in block}
    assert sock_services, (
        "docker.sock 执行通道未挂载:容器内无法触达 Docker 执行通道,"
        "重启任务即使被消费也会失败"
    )
    # 最小权限:docker.sock 只允许出现在运行重启 worker 的服务上
    assert sock_services <= workers, (
        f"docker.sock 挂载违反最小权限:仅 {sorted(workers)} 允许持有,"
        f"实际 {sorted(sock_services)}"
    )
    for name in sock_services:
        mounts = [
            line for line in services[name].splitlines() if DOCKER_SOCK in line
        ]
        assert mounts, f"服务 {name} 应以只读方式挂载 {DOCKER_SOCK}"
        assert any(
            re.search(rf"{re.escape(DOCKER_SOCK)}:\S*:ro(?:\s|#|$)", line)
            for line in mounts
        ), f"服务 {name} 的 docker.sock 挂载必须为只读(:ro):{mounts}"


def test_cognee_service_consumes_managed_runtime_env_file():
    """待应用配置生效链路的容器侧一环:cognee 服务消费受管 runtime env 文件。"""
    services = _service_blocks(COMPOSE_FILE)
    assert "cognee" in services, "docker-compose.yml 缺少 cognee 服务"
    assert ".scratch/cognee-runtime.env" in services["cognee"], (
        "cognee 服务未声明 env_file: .scratch/cognee-runtime.env,"
        "重启时写入的受管配置无法在重建后的容器中生效"
    )


def test_deployment_contract_requires_both_worker_and_channel():
    """防回归:worker 与 docker.sock 通道必须同时存在,缺一队列照样卡死。"""
    services = _service_blocks(COMPOSE_FILE)
    workers = _restart_worker_services(services)
    sock_services = {name for name, block in services.items() if DOCKER_SOCK in block}
    assert workers and sock_services and sock_services <= workers, (
        "worker 与 docker.sock 通道必须同时落在重启 worker 服务上;当前:"
        f"worker={sorted(workers)},sock={sorted(sock_services)}"
    )


# 部署缺陷(2026-08-30):通道 argv 只用根 docker-compose.yml 重建 cognee,生产
# 多文件 compose 组合(根 + prod + 环境专属覆盖层)下,prod 覆盖层注入的 cognee
# 安全加固(REQUIRE_AUTHENTICATION 等)在重建后丢失。生产重建必须与运行栈一致。
COMPOSE_FILES_SETTING = "COGNEE_COMPOSE_FILES"
PROD_REQUIRED_COMPOSE_FILES = ("docker-compose.yml", "deploy/docker-compose.prod.yml")


def _injected_compose_files_value(block: str) -> str:
    """提取 restart-worker 块内 COGNEE_COMPOSE_FILES 的原始值(兼容冒号/等号两种 env 写法)。"""
    match = re.search(
        rf"^\s*(?:-\s*)?{COMPOSE_FILES_SETTING}\s*[:=]\s*(.+?)\s*(?:#.*)?$",
        block,
        re.M,
    )
    return match.group(1).strip() if match else ""


def _resolved_default(value: str) -> str:
    """兼容 ${VAR:-default} 注入形式:取默认段;纯字面值原样返回。"""
    wrapper = re.fullmatch(r"\$\{[^}]*:-(.*)\}", value)
    return wrapper.group(1) if wrapper else value


def test_prod_override_injects_compose_file_list_for_restart_worker():
    """生产覆盖层必须为 restart-worker 注入 compose 文件列表,保证重建与运行栈一致。"""
    if not PROD_OVERRIDE_FILE.exists():
        pytest.fail(
            f"缺少生产 compose 覆盖层 {PROD_OVERRIDE_FILE.relative_to(REPO_ROOT)}"
        )
    services = _service_blocks(PROD_OVERRIDE_FILE)
    assert "restart-worker" in services, "生产覆盖层缺少 restart-worker 服务块"
    raw = _injected_compose_files_value(services["restart-worker"])
    assert raw, (
        f"生产覆盖层未为 restart-worker 注入 {COMPOSE_FILES_SETTING}:"
        "重建将退回仅根 docker-compose.yml,prod 覆盖层的 cognee 安全加固丢失"
    )
    resolved = _resolved_default(raw)
    for required in PROD_REQUIRED_COMPOSE_FILES:
        assert required in resolved, (
            f"{COMPOSE_FILES_SETTING} 解析默认值必须含 {required}"
            f"(根文件与生产覆盖层),实际:{resolved};"
            "环境专属覆盖层允许经部署 env 覆盖追加"
        )
