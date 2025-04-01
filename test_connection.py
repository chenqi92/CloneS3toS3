#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3连接测试脚本
用于测试源和目标S3存储的连接是否正常
"""

import os
import sys
import argparse
import boto3
import logging
from botocore.exceptions import ClientError
from main import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def create_s3_client(endpoint, access_key, secret_key):
    """创建S3客户端连接"""
    try:
        client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )
        return client
    except Exception as e:
        logger.error(f"创建S3客户端失败: {str(e)}")
        return None

def test_bucket_access(client, bucket_name):
    """测试对存储桶的访问权限"""
    try:
        # 尝试列出存储桶中的对象
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
        logger.info(f"成功访问存储桶 {bucket_name}")
        
        # 检查是否有对象
        if 'Contents' in response:
            first_object = response['Contents'][0]['Key'] if response['Contents'] else "无对象"
            logger.info(f"存储桶中的第一个对象: {first_object}")
        else:
            logger.info(f"存储桶 {bucket_name} 为空")
        
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"访问存储桶 {bucket_name} 失败: {error_code} - {error_message}")
        return False

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='测试S3存储连接')
    parser.add_argument('-c', '--config', default='config.ini', help='配置文件路径')
    parser.add_argument('-b', '--buckets', help='要测试的存储桶，逗号分隔')
    parser.add_argument('--source-only', action='store_true', help='仅测试源存储')
    parser.add_argument('--target-only', action='store_true', help='仅测试目标存储')
    return parser.parse_args()

def main():
    """主函数"""
    args = parse_arguments()
    
    try:
        # 加载配置
        config = load_config(args.config)
        
        # 获取测试的存储桶列表
        if args.buckets:
            buckets = args.buckets.split(',')
        elif 'migration' in config and 'buckets' in config['migration']:
            buckets = config['migration']['buckets'].split(',')
        else:
            logger.error("未指定要测试的存储桶。请在配置文件中添加buckets参数或使用--buckets参数指定")
            return
        
        # 测试源存储
        if not args.target_only:
            logger.info("===== 测试源存储连接 =====")
            source_client = create_s3_client(
                config['source']['endpoint'],
                config['source']['access_key'],
                config['source']['secret_key']
            )
            
            if source_client:
                logger.info("源存储连接创建成功")
                for bucket in buckets:
                    test_bucket_access(source_client, bucket.strip())
            else:
                logger.error("无法连接到源存储")
        
        # 测试目标存储
        if not args.source_only:
            logger.info("\n===== 测试目标存储连接 =====")
            target_client = create_s3_client(
                config['target']['endpoint'],
                config['target']['access_key'],
                config['target']['secret_key']
            )
            
            if target_client:
                logger.info("目标存储连接创建成功")
                for bucket in buckets:
                    test_bucket_access(target_client, bucket.strip())
            else:
                logger.error("无法连接到目标存储")
                
    except Exception as e:
        logger.error(f"测试过程中发生错误: {str(e)}")

if __name__ == "__main__":
    main() 