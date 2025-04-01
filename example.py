#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3桶迁移工具使用示例
演示如何调用main.py脚本或使用S3Migrator类
"""

import os
import sys
import logging
from main import S3Migrator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_cli_usage():
    """演示如何通过命令行使用工具"""
    logger.info("示例1: 通过命令行参数使用工具")
    logger.info("python main.py --source-endpoint http://source-s3.example.com --source-access-key source_key --source-secret-key source_secret --target-endpoint http://target-s3.example.com --target-access-key target_key --target-secret-key target_secret --buckets bucket1,bucket2")
    
    logger.info("\n示例2: 使用配置文件")
    logger.info("python main.py --config config.ini")
    
    logger.info("\n示例3: 混合使用配置文件和命令行参数")
    logger.info("python main.py --config config.ini --max-workers 20")


def example_programmatic_usage():
    """演示如何在程序中使用S3Migrator类"""
    # 仅演示代码，不实际执行
    logger.info("以下是如何在您自己的Python代码中使用S3Migrator类的示例:")
    
    code_example = """
    from main import S3Migrator
    
    # 创建迁移器实例
    migrator = S3Migrator(
        source_endpoint="http://source-s3.example.com",
        source_access_key="source_access_key",
        source_secret_key="source_secret_key",
        target_endpoint="http://target-s3.example.com",
        target_access_key="target_access_key",
        target_secret_key="target_secret_key",
        bucket_names=["bucket1", "bucket2", "bucket3"],
        max_workers=10,
        chunk_size=8 * 1024 * 1024  # 8MB
    )
    
    # 执行所有桶的迁移
    total_objects, total_bytes = migrator.migrate_all_buckets()
    print(f"迁移完成: {total_objects} 个对象, 总大小: {migrator._format_size(total_bytes)}")
    
    # 或者，只迁移单个桶
    objects, bytes_copied = migrator.migrate_bucket("specific-bucket")
    print(f"桶迁移完成: {objects} 个对象, 大小: {migrator._format_size(bytes_copied)}")
    """
    
    logger.info(code_example)


def display_config_example():
    """显示配置文件示例"""
    config_example = """
[source]
endpoint = http://source-s3.example.com
access_key = source_access_key
secret_key = source_secret_key

[target]
endpoint = http://target-s3.example.com
access_key = target_access_key
secret_key = target_secret_key

[migration]
buckets = bucket1,bucket2,bucket3
max_workers = 10
chunk_size = 8388608
"""
    
    logger.info("配置文件示例 (config.ini):")
    logger.info(config_example)


if __name__ == "__main__":
    print("=" * 80)
    print("S3桶迁移工具使用示例")
    print("=" * 80)
    print()
    
    example_cli_usage()
    print("\n" + "-" * 80 + "\n")
    
    example_programmatic_usage()
    print("\n" + "-" * 80 + "\n")
    
    display_config_example()
    print("\n" + "=" * 80) 