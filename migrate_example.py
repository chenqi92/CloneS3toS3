#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3对象存储迁移示例脚本
此脚本演示了如何使用main.py中的CloneS3类进行对象存储迁移
"""

import os
import sys
import logging
from main import CloneS3

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def main():
    """迁移示例脚本的主函数"""
    # 源S3配置
    source_config = {
        'endpoint': 'https://your-source-endpoint.com',
        'access_key': 'your_source_access_key',
        'secret_key': 'your_source_secret_key',
        'is_r2': False
    }
    
    # 目标S3配置
    target_config = {
        'endpoint': 'https://your-target-endpoint.com',
        'access_key': 'your_target_access_key',
        'secret_key': 'your_target_secret_key'
    }
    
    # 迁移配置
    migration_config = {
        'buckets': ['bucket1', 'bucket2'],  # 要迁移的存储桶列表
        'max_workers': 10,                  # 最大工作线程数
        'chunk_size': 8 * 1024 * 1024,      # 分块大小 (8MB)
        'direct_read': True,                # 是否直接读取文件
        'max_direct_size': 500 * 1024 * 1024 # 直接读取的最大文件大小 (500MB)
    }
    
    # 创建CloneS3实例
    clone = CloneS3(
        source_endpoint=source_config['endpoint'],
        source_access_key=source_config['access_key'],
        source_secret_key=source_config['secret_key'],
        source_is_r2=source_config['is_r2'],
        target_endpoint=target_config['endpoint'],
        target_access_key=target_config['access_key'],
        target_secret_key=target_config['secret_key'],
        max_workers=migration_config['max_workers'],
        chunk_size=migration_config['chunk_size'],
        direct_read=migration_config['direct_read'],
        max_direct_size=migration_config['max_direct_size']
    )
    
    # 执行迁移
    buckets_to_migrate = migration_config['buckets']
    print(f"开始迁移以下存储桶: {', '.join(buckets_to_migrate)}")
    
    results = clone.migrate_all_buckets(buckets_to_migrate)
    
    # 打印迁移结果
    print("\n迁移结果摘要:")
    for bucket, stats in results.items():
        print(f"\n存储桶: {bucket}")
        print(f"  成功: {stats['success']} 个对象")
        print(f"  失败: {stats['failed']} 个对象")
        print(f"  总大小: {clone.format_size(stats['size'])}")
        
        if stats['failed_objects']:
            print(f"\n  失败对象列表:")
            for obj, error in stats['failed_objects'].items():
                print(f"    - {obj}: {error}")

if __name__ == "__main__":
    main() 