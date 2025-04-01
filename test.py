#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3桶迁移工具测试脚本
测试程序的基本功能和参数解析
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 从主模块导入函数
from main import S3Migrator, load_config, parse_arguments

class TestS3Migrator(unittest.TestCase):
    """测试S3Migrator类"""
    
    def setUp(self):
        """测试初始化"""
        # 模拟S3客户端
        self.mock_s3_client = MagicMock()
        
        # 设置测试参数
        self.source_endpoint = "http://source-s3.example.com"
        self.source_access_key = "source_access_key"
        self.source_secret_key = "source_secret_key"
        self.target_endpoint = "http://target-s3.example.com"
        self.target_access_key = "target_access_key"
        self.target_secret_key = "target_secret_key"
        self.bucket_names = ["test-bucket"]
        self.max_workers = 5
        self.chunk_size = 1024 * 1024  # 1MB
    
    @patch('boto3.client')
    def test_init(self, mock_boto3_client):
        """测试初始化方法"""
        # 设置模拟返回值
        mock_boto3_client.return_value = self.mock_s3_client
        
        # 创建测试实例
        migrator = S3Migrator(
            source_endpoint=self.source_endpoint,
            source_access_key=self.source_access_key,
            source_secret_key=self.source_secret_key,
            target_endpoint=self.target_endpoint,
            target_access_key=self.target_access_key,
            target_secret_key=self.target_secret_key,
            bucket_names=self.bucket_names,
            max_workers=self.max_workers,
            chunk_size=self.chunk_size
        )
        
        # 验证初始化
        self.assertEqual(migrator.source_endpoint, self.source_endpoint)
        self.assertEqual(migrator.source_access_key, self.source_access_key)
        self.assertEqual(migrator.source_secret_key, self.source_secret_key)
        self.assertEqual(migrator.target_endpoint, self.target_endpoint)
        self.assertEqual(migrator.target_access_key, self.target_access_key)
        self.assertEqual(migrator.target_secret_key, self.target_secret_key)
        self.assertEqual(migrator.bucket_names, self.bucket_names)
        self.assertEqual(migrator.max_workers, self.max_workers)
        self.assertEqual(migrator.chunk_size, self.chunk_size)
        
        # 验证客户端创建
        mock_boto3_client.assert_any_call(
            's3',
            endpoint_url=self.source_endpoint,
            aws_access_key_id=self.source_access_key,
            aws_secret_access_key=self.source_secret_key
        )
        mock_boto3_client.assert_any_call(
            's3',
            endpoint_url=self.target_endpoint,
            aws_access_key_id=self.target_access_key,
            aws_secret_access_key=self.target_secret_key
        )
    
    @patch('boto3.client')
    def test_format_size(self, mock_boto3_client):
        """测试格式化大小方法"""
        # 设置模拟返回值
        mock_boto3_client.return_value = self.mock_s3_client
        
        # 创建测试实例
        migrator = S3Migrator(
            source_endpoint=self.source_endpoint,
            source_access_key=self.source_access_key,
            source_secret_key=self.source_secret_key,
            target_endpoint=self.target_endpoint,
            target_access_key=self.target_access_key,
            target_secret_key=self.target_secret_key,
            bucket_names=self.bucket_names
        )
        
        # 测试不同大小
        self.assertEqual(migrator._format_size(0), "0B")
        self.assertEqual(migrator._format_size(1024), "1.0 KB")
        self.assertEqual(migrator._format_size(1024*1024), "1.0 MB")
        self.assertEqual(migrator._format_size(1024*1024*1024), "1.0 GB")


class TestConfigFunctions(unittest.TestCase):
    """测试配置相关函数"""
    
    def setUp(self):
        """测试初始化"""
        # 创建临时配置文件
        self.config_content = """
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
max_workers = 15
chunk_size = 16777216
"""
        self.config_file = "test_config.ini"
        with open(self.config_file, "w") as f:
            f.write(self.config_content)
    
    def tearDown(self):
        """测试清理"""
        # 删除临时配置文件
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
    
    def test_load_config(self):
        """测试配置加载函数"""
        config = load_config(self.config_file)
        
        # 验证配置
        self.assertEqual(config["source_endpoint"], "http://source-s3.example.com")
        self.assertEqual(config["source_access_key"], "source_access_key")
        self.assertEqual(config["source_secret_key"], "source_secret_key")
        self.assertEqual(config["target_endpoint"], "http://target-s3.example.com")
        self.assertEqual(config["target_access_key"], "target_access_key")
        self.assertEqual(config["target_secret_key"], "target_secret_key")
        self.assertEqual(config["buckets"], ["bucket1", "bucket2", "bucket3"])
        self.assertEqual(config["max_workers"], 15)
        self.assertEqual(config["chunk_size"], 16777216)
    
    def test_load_config_nonexistent(self):
        """测试加载不存在的配置文件"""
        config = load_config("nonexistent_config.ini")
        self.assertEqual(config, {})
    
    def test_parse_arguments(self):
        """测试参数解析函数"""
        # 模拟命令行参数
        test_args = [
            "--source-endpoint", "http://test-source.com",
            "--source-access-key", "test_source_key",
            "--source-secret-key", "test_source_secret",
            "--target-endpoint", "http://test-target.com",
            "--target-access-key", "test_target_key",
            "--target-secret-key", "test_target_secret",
            "--buckets", "bucket-a,bucket-b",
            "--max-workers", "12",
            "--chunk-size", "4194304"
        ]
        
        with patch('sys.argv', ['test.py'] + test_args):
            args = parse_arguments()
            
            # 验证解析结果
            self.assertEqual(args.source_endpoint, "http://test-source.com")
            self.assertEqual(args.source_access_key, "test_source_key")
            self.assertEqual(args.source_secret_key, "test_source_secret")
            self.assertEqual(args.target_endpoint, "http://test-target.com")
            self.assertEqual(args.target_access_key, "test_target_key")
            self.assertEqual(args.target_secret_key, "test_target_secret")
            self.assertEqual(args.buckets, "bucket-a,bucket-b")
            self.assertEqual(args.max_workers, 12)
            self.assertEqual(args.chunk_size, 4194304)


if __name__ == "__main__":
    unittest.main() 