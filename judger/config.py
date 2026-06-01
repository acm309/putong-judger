from pathlib import Path

# Logger 名称
LOGGER_NAME = 'judger'
# 任务队列名称
TASK_QUEUE_NAME = 'judger:task'
# 结果队列名称
RESULT_QUEUE_NAME = 'judger:result'
# CPU 时间限制，单位纳秒 (10 秒)
DEFAULT_TIME_LIMIT = 10_000_000_000
# 内存限制，单位 Byte (512MB)
DEFAULT_MEMORY_LIMIT = 512 * 1024 * 1024
# 线程数量限制
DEFAULT_PROC_LIMIT = 64
# CPU 使用率限制，1000 等于单核 100%
DEFAULT_CPU_RATE_LIMIT = 1000
# 输出限制，单位 Byte (16MB)
DEFAULT_OUTPUT_LIMIT = 16 * 1024 * 1024
# 默认检查器
DEFAULT_CHECKER = Path(__file__).parent / 'checkers' / 'lcmp.cpp'
# 默认检查器代码内容
DEFAULT_CHECKER_CODE = DEFAULT_CHECKER.read_text(encoding='utf-8')
# 测试库路径
TESTLIB_PATH = Path(__file__).parent / "testlib" / "testlib.h"
# 默认沙箱环境变量
DEFAULT_SANDBOX_ENV = ["PATH=/usr/bin:/bin", "ONLINE_JUDGE=1"]
