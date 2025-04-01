#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3桶迁移工具
将一个S3存储库中的所有内容迁移到另一个S3存储库
支持多线程、多桶、多层级目录结构
"""

import os
import sys
import time
import math
import logging
import argparse
import configparser
import concurrent.futures
from typing import List, Dict, Tuple, Optional, Callable
import boto3
from botocore.exceptions import ClientError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 可重试的错误代码
RETRIABLE_ERROR_CODES = [
    'RequestTimeout',
    'RequestTimeTooSkewed',
    'InternalError',
    'ServiceUnavailable',
    'SlowDown',
    'OperationAborted',
    'ConnectionError',
    'ConnectTimeoutError',
    'ReadTimeoutError'
]

def retry_operation(func: Callable, *args, max_retries: int = 3, retry_delay: int = 2, **kwargs):
    """
    重试操作函数，用于在出现临时错误时重试
    
    Args:
        func: 要重试的函数
        *args: 函数的位置参数
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        **kwargs: 函数的关键字参数
    
    Returns:
        函数的返回值
    """
    retry_count = 0
    last_exception = None
    
    while retry_count < max_retries:
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            # 检查是否是可重试的错误
            if error_code in RETRIABLE_ERROR_CODES:
                retry_count += 1
                wait_time = retry_delay * (2 ** (retry_count - 1))  # 指数退避
                logger.warning(f"遇到可重试错误 {error_code}，将在 {wait_time} 秒后进行第 {retry_count} 次重试...")
                time.sleep(wait_time)
                last_exception = e
            else:
                # 不可重试的错误直接抛出
                raise
        except (ConnectionError, TimeoutError) as e:
            # 网络相关错误
            retry_count += 1
            wait_time = retry_delay * (2 ** (retry_count - 1))
            logger.warning(f"遇到网络错误，将在 {wait_time} 秒后进行第 {retry_count} 次重试...")
            time.sleep(wait_time)
            last_exception = e
    
    # 如果达到最大重试次数，抛出最后一个异常
    if last_exception:
        logger.error(f"重试 {max_retries} 次后操作仍然失败")
        raise last_exception
    
    return None

class S3Migrator:
    """S3存储库迁移工具"""
    
    def __init__(
        self, 
        source_endpoint: str,
        source_access_key: str,
        source_secret_key: str,
        target_endpoint: str,
        target_access_key: str,
        target_secret_key: str,
        bucket_names: List[str],
        max_workers: int = 10,
        chunk_size: int = 8 * 1024 * 1024,  # 8MB
        is_source_r2: bool = False,
        direct_read: bool = False,
        max_direct_size: int = 500 * 1024 * 1024,  # 默认500MB，超过此大小的文件使用分块上传
        skip_existing: bool = True  # 默认跳过已存在的文件
    ):
        """
        初始化S3迁移器
        
        Args:
            source_endpoint: 源S3端点URL
            source_access_key: 源S3访问密钥
            source_secret_key: 源S3秘密密钥
            target_endpoint: 目标S3端点URL
            target_access_key: 目标S3访问密钥
            target_secret_key: 目标S3秘密密钥
            bucket_names: 要迁移的桶名列表
            max_workers: 最大工作线程数
            chunk_size: 分块上传大小
            is_source_r2: 源存储是否是Cloudflare R2
            direct_read: 是否直接读取所有文件，不使用分块处理
            max_direct_size: 直接读取的最大文件大小，超过此大小的文件使用分块上传
            skip_existing: 是否跳过已存在的文件
        """
        self.source_endpoint = source_endpoint
        self.source_access_key = source_access_key
        self.source_secret_key = source_secret_key
        
        self.target_endpoint = target_endpoint
        self.target_access_key = target_access_key
        self.target_secret_key = target_secret_key
        
        self.bucket_names = bucket_names
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.is_source_r2 = is_source_r2
        self.direct_read = direct_read
        self.max_direct_size = max_direct_size
        self.skip_existing = skip_existing
        
        # 初始化源S3客户端
        self.source_client = boto3.client(
            's3',
            endpoint_url=source_endpoint,
            aws_access_key_id=source_access_key,
            aws_secret_access_key=source_secret_key,
            config=boto3.session.Config(
                signature_version='s3v4',  # 确保使用最新的签名版本
                s3={'addressing_style': 'virtual'}  # 使用虚拟主机样式
            )
        )
        
        # 初始化目标S3客户端
        self.target_client = boto3.client(
            's3',
            endpoint_url=target_endpoint,
            aws_access_key_id=target_access_key,
            aws_secret_access_key=target_secret_key
        )
    
    def migrate_all_buckets(self):
        """迁移所有指定的桶"""
        start_time = time.time()
        total_objects = 0
        total_failed = 0
        total_bytes = 0
        failures_by_bucket = {}
        
        logger.info(f"开始迁移 {len(self.bucket_names)} 个桶...")
        
        for bucket_name in self.bucket_names:
            try:
                # 确保目标桶存在
                self._ensure_bucket_exists(bucket_name)
                
                # 迁移单个桶
                objects, bytes_copied = self.migrate_bucket(bucket_name)
                total_objects += objects
                total_bytes += bytes_copied
                
                # 计算该桶的失败对象数量
                objects_list = self._list_all_objects(bucket_name)
                bucket_total = len(objects_list)
                failed = bucket_total - objects
                total_failed += failed
                
                if failed > 0:
                    failures_by_bucket[bucket_name] = failed
                
                logger.info(f"桶 {bucket_name} 迁移完成，成功: {objects}/{bucket_total}，失败: {failed}")
            except Exception as e:
                logger.error(f"迁移桶 {bucket_name} 时出错: {str(e)}")
                total_failed += 1  # 整个桶迁移失败，至少计为1个失败
                failures_by_bucket[bucket_name] = "整个桶迁移失败"
        
        elapsed_time = time.time() - start_time
        success_rate = (total_objects / (total_objects + total_failed)) * 100 if (total_objects + total_failed) > 0 else 0
        
        # 总结报告
        logger.info(f"迁移完成. 总计处理对象: {total_objects + total_failed}, "
                  f"成功: {total_objects} ({success_rate:.1f}%), "
                  f"失败: {total_failed}, "
                  f"总大小: {self._format_size(total_bytes)}, "
                  f"耗时: {elapsed_time:.2f}秒")
        
        if failures_by_bucket:
            logger.warning("失败统计 (按桶):")
            for bucket, count in failures_by_bucket.items():
                logger.warning(f"  - {bucket}: {count}")
            
            # 建议用户查看详细日志
            logger.info("请查看日志文件了解详细的失败对象列表")
        
        return total_objects, total_bytes, total_failed
    
    def migrate_bucket(self, bucket_name: str) -> Tuple[int, int]:
        """
        迁移单个桶的所有内容
        
        Args:
            bucket_name: 桶名称
            
        Returns:
            迁移的对象数量和总字节数的元组
        """
        logger.info(f"开始迁移桶: {bucket_name}")
        
        objects_list = self._list_all_objects(bucket_name)
        total_objects = len(objects_list)
        logger.info(f"在桶 {bucket_name} 中找到 {total_objects} 个对象")
        
        if total_objects == 0:
            return 0, 0
        
        copied_objects = 0
        failed_objects = 0
        total_bytes = 0
        failed_keys = []
        
        # 使用线程池并行复制对象
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_key = {
                executor.submit(self._copy_object, bucket_name, obj): obj 
                for obj in objects_list
            }
            
            for future in concurrent.futures.as_completed(future_to_key):
                obj = future_to_key[future]
                try:
                    copied, size = future.result()
                    if copied:
                        copied_objects += 1
                        total_bytes += size
                    else:
                        failed_objects += 1
                        failed_keys.append(obj['Key'])
                    
                    # 输出进度
                    processed = copied_objects + failed_objects
                    if processed % 10 == 0 or processed == total_objects:
                        logger.info(f"进度: {processed}/{total_objects} ({processed/total_objects*100:.1f}%), "
                                  f"成功: {copied_objects}, 失败: {failed_objects}, "
                                  f"总计: {self._format_size(total_bytes)}")
                except Exception as e:
                    failed_objects += 1
                    failed_keys.append(obj['Key'])
                    logger.error(f"复制对象 {obj['Key']} 时出错: {str(e)}")
        
        # 记录迁移结果
        logger.info(f"桶 {bucket_name} 迁移完成: 成功 {copied_objects}/{total_objects} 个对象, "
                  f"失败 {failed_objects} 个对象, 总大小: {self._format_size(total_bytes)}")
        
        # 如果有失败的对象，记录它们的键
        if failed_objects > 0:
            if failed_objects <= 10:
                logger.warning(f"失败的对象: {', '.join(failed_keys)}")
            else:
                logger.warning(f"失败的前10个对象: {', '.join(failed_keys[:10])}...")
                logger.warning(f"共 {failed_objects} 个对象迁移失败")
                
                # 将失败的键写入日志文件
                failed_log_file = f"failed_objects_{bucket_name}_{int(time.time())}.txt"
                try:
                    with open(failed_log_file, 'w') as f:
                        for key in failed_keys:
                            f.write(f"{key}\n")
                    logger.info(f"已将失败的对象列表写入文件: {failed_log_file}")
                except Exception as e:
                    logger.error(f"写入失败对象列表时出错: {str(e)}")
        
        return copied_objects, total_bytes
    
    def _ensure_bucket_exists(self, bucket_name: str):
        """确保目标桶存在，如不存在则创建"""
        try:
            retry_operation(self.target_client.head_bucket, Bucket=bucket_name)
            logger.info(f"目标桶 {bucket_name} 已存在")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                # 桶不存在，创建它
                logger.info(f"目标桶 {bucket_name} 不存在，正在创建...")
                retry_operation(self.target_client.create_bucket, Bucket=bucket_name)
                logger.info(f"目标桶 {bucket_name} 创建成功")
            else:
                # 其他错误
                raise
    
    def _list_all_objects(self, bucket_name: str) -> List[Dict]:
        """
        列出桶中的所有对象
        
        Args:
            bucket_name: 桶名称
            
        Returns:
            对象字典列表
        """
        objects = []
        paginator = self.source_client.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=bucket_name):
            if 'Contents' in page:
                objects.extend(page['Contents'])
        
        return objects
    
    def _copy_object(self, bucket_name: str, obj: Dict) -> Tuple[bool, int]:
        """
        复制单个对象从源桶到目标桶
        
        Args:
            bucket_name: 桶名称
            obj: 对象信息字典
            
        Returns:
            成功标志和对象大小的元组
        """
        key = obj['Key']
        size = obj['Size']
        
        # 首先检查目标存储中是否已存在该文件（仅当skip_existing为True时）
        if self.skip_existing:
            try:
                # 检查是否为文件夹（S3中通常以"/"结尾）
                if key.endswith('/'):
                    # 文件夹对象，直接处理
                    pass
                else:
                    # 尝试检查文件是否已存在
                    try:
                        # 使用head_object检查文件是否存在
                        response = retry_operation(
                            self.target_client.head_object,
                            Bucket=bucket_name,
                            Key=key
                        )
                        
                        # 如果执行到这里，说明文件存在，检查大小是否一致
                        target_size = response.get('ContentLength', 0)
                        
                        # 如果大小一致，则认为是相同文件，跳过
                        if target_size == size:
                            logger.info(f"文件已存在且大小一致，跳过: {key} (大小: {self._format_size(size)})")
                            return True, size
                        else:
                            logger.info(f"文件已存在但大小不一致，将覆盖: {key} (源: {self._format_size(size)}, 目标: {self._format_size(target_size)})")
                    except ClientError as e:
                        # 文件不存在，继续上传
                        error_code = e.response.get('Error', {}).get('Code')
                        if error_code == 'NoSuchKey' or error_code == '404' or error_code == '403':
                            # 文件不存在，继续处理
                            pass
                        else:
                            # 其他错误
                            raise
            except Exception as e:
                # 检查过程中出错，记录日志但继续尝试上传
                logger.warning(f"检查文件 {key} 是否存在时出错: {str(e)}")
        
        # 如果配置了直接读取模式，或者文件大小在可接受范围内
        if self.direct_read or size <= self.max_direct_size:
            try:
                logger.info(f"开始直接复制对象: {key} (大小: {self._format_size(size)})")
                
                # 直接获取对象内容
                response = retry_operation(
                    self.source_client.get_object,
                    Bucket=bucket_name,
                    Key=key
                )
                
                # 读取对象数据
                data = response['Body'].read()
                
                # 上传到目标存储
                retry_operation(
                    self.target_client.put_object,
                    Bucket=bucket_name,
                    Key=key,
                    Body=data
                )
                
                logger.info(f"成功复制对象: {key}")
                return True, size
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                if error_code == 'NoSuchKey' or error_code == '404':
                    logger.warning(f"复制对象 {key} 时出错: 文件不存在 (NoSuchKey)")
                else:
                    logger.error(f"复制对象 {key} 时出错: {error_code} - {str(e)}")
                return False, 0
            except Exception as e:
                logger.error(f"复制对象 {key} 时出错: {str(e)}")
                return False, 0
        else:
            # 对于超大文件，使用分块上传
            return self._multipart_copy(bucket_name, key, size)
    
    def _multipart_copy(self, bucket_name: str, key: str, size: int) -> Tuple[bool, int]:
        """
        大文件分块复制方法
        
        Args:
            bucket_name: 桶名称
            key: 对象键名
            size: 对象大小
            
        Returns:
            成功标志和对象大小的元组
        """
        # 再次检查文件是否已存在，因为可能在_copy_object方法判断后状态已变化（仅当skip_existing为True时）
        if self.skip_existing:
            try:
                # 跳过文件夹对象
                if not key.endswith('/'):
                    try:
                        response = retry_operation(
                            self.target_client.head_object,
                            Bucket=bucket_name,
                            Key=key
                        )
                        target_size = response.get('ContentLength', 0)
                        if target_size == size:
                            logger.info(f"大文件已存在且大小一致，跳过分块上传: {key} (大小: {self._format_size(size)})")
                            return True, size
                        else:
                            logger.info(f"大文件已存在但大小不一致，将覆盖: {key} (源: {self._format_size(size)}, 目标: {self._format_size(target_size)})")
                    except ClientError as e:
                        error_code = e.response.get('Error', {}).get('Code')
                        if error_code not in ['NoSuchKey', '404', '403']:
                            raise
            except Exception as e:
                logger.warning(f"检查大文件 {key} 是否存在时出错: {str(e)}")
        
        try:
            logger.info(f"开始分块复制大文件: {key} (大小: {self._format_size(size)})")
            
            # 初始化分块上传
            multipart_upload = retry_operation(
                self.target_client.create_multipart_upload,
                Bucket=bucket_name,
                Key=key
            )
            upload_id = multipart_upload['UploadId']
            
            # 计算分块数量
            part_count = (size + self.chunk_size - 1) // self.chunk_size
            
            # 上传每个分块
            parts = []
            for i in range(part_count):
                start_byte = i * self.chunk_size
                end_byte = min(start_byte + self.chunk_size - 1, size - 1)
                
                # 从源获取并上传到目标
                part_number = i + 1
                range_str = f'bytes={start_byte}-{end_byte}'
                
                try:
                    # 获取源对象的一部分
                    response = retry_operation(
                        self.source_client.get_object,
                        Bucket=bucket_name,
                        Key=key,
                        Range=range_str
                    )
                    
                    # 上传分块
                    part = retry_operation(
                        self.target_client.upload_part,
                        Body=response['Body'].read(),
                        Bucket=bucket_name,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id
                    )
                    
                    parts.append({
                        'ETag': part['ETag'],
                        'PartNumber': part_number
                    })
                    
                    if part_number % 10 == 0 or part_number == part_count:
                        logger.info(f"分块上传进度 {key}: {part_number}/{part_count} ({part_number/part_count*100:.1f}%)")
                except Exception as e:
                    logger.error(f"上传分块 {part_number}/{part_count} 时出错: {str(e)}")
                    raise
            
            # 完成分块上传
            retry_operation(
                self.target_client.complete_multipart_upload,
                Bucket=bucket_name,
                Key=key,
                MultipartUpload={'Parts': parts},
                UploadId=upload_id
            )
            
            logger.info(f"成功分块复制大文件: {key}")
            return True, size
        except Exception as e:
            logger.error(f"分块上传对象 {key} 时出错: {str(e)}")
            # 尝试中止分块上传
            try:
                if 'upload_id' in locals():
                    retry_operation(
                        self.target_client.abort_multipart_upload,
                        Bucket=bucket_name,
                        Key=key,
                        UploadId=upload_id
                    )
            except Exception as abort_error:
                logger.error(f"中止分块上传时出错: {str(abort_error)}")
            return False, 0
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化字节大小为人类可读格式"""
        if size_bytes == 0:
            return "0B"
        size_names = ("B", "KB", "MB", "GB", "TB", "PB")
        i = int(math.log(size_bytes, 1024))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"


def load_config(config_file: str) -> Dict:
    """
    从配置文件加载配置
    
    Args:
        config_file: 配置文件路径
        
    Returns:
        配置字典
    """
    if not os.path.exists(config_file):
        logger.error(f"配置文件 {config_file} 不存在")
        return {}
    
    config = configparser.ConfigParser()
    
    # 尝试使用UTF-8编码读取
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config.read_file(f)
            logger.info(f"成功使用UTF-8编码读取配置文件: {config_file}")
    except UnicodeDecodeError:
        # 尝试使用GBK编码
        try:
            with open(config_file, 'r', encoding='gbk') as f:
                config.read_file(f)
                logger.info(f"成功使用GBK编码读取配置文件: {config_file}")
        except Exception as e:
            logger.error(f"无法读取配置文件 {config_file}: {str(e)}")
            logger.error("请尝试运行 'python fix_encoding.py' 修复配置文件编码问题")
            return {}
    except Exception as e:
        logger.error(f"读取配置文件时出错: {str(e)}")
        return {}
    
    # 验证必要的配置部分是否存在
    required_sections = ["source", "target", "migration"]
    for section in required_sections:
        if section not in config:
            logger.error(f"配置文件缺少必要的部分: {section}")
            return {}
    
    # 提取配置
    result = {
        "source_endpoint": config.get("source", "endpoint"),
        "source_access_key": config.get("source", "access_key"),
        "source_secret_key": config.get("source", "secret_key"),
        "target_endpoint": config.get("target", "endpoint"),
        "target_access_key": config.get("target", "access_key"),
        "target_secret_key": config.get("target", "secret_key"),
        "buckets": [b.strip() for b in config.get("migration", "buckets").split(",") if b.strip()],
        "max_workers": config.getint("migration", "max_workers", fallback=10),
        "chunk_size": config.getint("migration", "chunk_size", fallback=8*1024*1024),
        "is_source_r2": config.getboolean("source", "is_r2", fallback=False),
        "direct_read": config.getboolean("source", "direct_read", fallback=False),
        "max_direct_size": config.getint("source", "max_direct_size", fallback=500*1024*1024),
        "skip_existing": config.getboolean("source", "skip_existing", fallback=True)
    }
    
    return result


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='S3存储库迁移工具')
    
    # 配置文件选项
    parser.add_argument('--config', help='配置文件路径')
    
    # S3源配置
    parser.add_argument('--source-endpoint', help='源S3端点URL')
    parser.add_argument('--source-access-key', help='源S3访问密钥')
    parser.add_argument('--source-secret-key', help='源S3秘密密钥')
    parser.add_argument('--is-source-r2', action='store_true', help='源存储是否为Cloudflare R2')
    parser.add_argument('--direct-read', action='store_true', help='是否直接读取所有文件，不使用分块处理')
    parser.add_argument('--max-direct-size', type=int, default=500*1024*1024, help='直接读取的最大文件大小，超过此大小的文件使用分块上传 (默认: 500MB)')
    parser.add_argument('--no-skip-existing', action='store_true', help='是否不跳过目标存储中已存在的文件，强制重新上传')
    
    # S3目标配置
    parser.add_argument('--target-endpoint', help='目标S3端点URL')
    parser.add_argument('--target-access-key', help='目标S3访问密钥')
    parser.add_argument('--target-secret-key', help='目标S3秘密密钥')
    
    # 迁移配置
    parser.add_argument('--buckets', help='要迁移的桶名列表，用逗号分隔')
    parser.add_argument('--max-workers', type=int, default=10, help='最大工作线程数 (默认: 10)')
    parser.add_argument('--chunk-size', type=int, default=8*1024*1024, help='分块上传大小，单位字节 (默认: 8MB)')
    
    return parser.parse_args()


def main():
    """主函数"""
    import math  # 用于格式化大小
    
    # 解析命令行参数
    args = parse_arguments()
    
    # 配置字典
    config = {}
    
    # 如果指定了配置文件，加载配置
    if args.config:
        config = load_config(args.config)
        if not config:
            logger.error("配置加载失败，退出程序")
            sys.exit(1)
    
    # 优先使用命令行参数，然后是配置文件
    source_endpoint = args.source_endpoint or config.get("source_endpoint")
    source_access_key = args.source_access_key or config.get("source_access_key")
    source_secret_key = args.source_secret_key or config.get("source_secret_key")
    
    target_endpoint = args.target_endpoint or config.get("target_endpoint")
    target_access_key = args.target_access_key or config.get("target_access_key")
    target_secret_key = args.target_secret_key or config.get("target_secret_key")
    
    # 处理桶名列表
    if args.buckets:
        bucket_names = [b.strip() for b in args.buckets.split(',') if b.strip()]
    else:
        bucket_names = config.get("buckets", [])
    
    # 处理其他参数
    max_workers = args.max_workers if args.max_workers != 10 else config.get("max_workers", 10)
    chunk_size = args.chunk_size if args.chunk_size != 8*1024*1024 else config.get("chunk_size", 8*1024*1024)
    is_source_r2 = args.is_source_r2 or config.get("is_source_r2", False)
    direct_read = args.direct_read or config.get("direct_read", False)
    max_direct_size = args.max_direct_size if args.max_direct_size != 500*1024*1024 else config.get("max_direct_size", 500*1024*1024)
    skip_existing = not args.no_skip_existing if hasattr(args, 'no_skip_existing') else config.get("skip_existing", True)
    
    # 验证必要的参数是否存在
    missing_args = []
    if not source_endpoint:
        missing_args.append("source-endpoint")
    if not source_access_key:
        missing_args.append("source-access-key")
    if not source_secret_key:
        missing_args.append("source-secret-key")
    if not target_endpoint:
        missing_args.append("target-endpoint")
    if not target_access_key:
        missing_args.append("target-access-key")
    if not target_secret_key:
        missing_args.append("target-secret-key")
    if not bucket_names:
        missing_args.append("buckets")
    
    if missing_args:
        logger.error(f"缺少必要的参数: {', '.join(missing_args)}")
        logger.error("请指定这些参数或提供包含这些参数的配置文件")
        sys.exit(1)
    
    # 创建迁移器实例
    migrator = S3Migrator(
        source_endpoint=source_endpoint,
        source_access_key=source_access_key,
        source_secret_key=source_secret_key,
        target_endpoint=target_endpoint,
        target_access_key=target_access_key,
        target_secret_key=target_secret_key,
        bucket_names=bucket_names,
        max_workers=max_workers,
        chunk_size=chunk_size,
        is_source_r2=is_source_r2,
        direct_read=direct_read,
        max_direct_size=max_direct_size,
        skip_existing=skip_existing
    )
    
    # 执行迁移
    try:
        total_objects, total_bytes, total_failed = migrator.migrate_all_buckets()
        logger.info(f"成功迁移 {total_objects} 个对象，总大小: {migrator._format_size(total_bytes)}")
        sys.exit(0)
    except KeyboardInterrupt:
        logger.info("迁移被用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"迁移过程出错: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()

# 访问 https://www.jetbrains.com/help/pycharm/ 获取 PyCharm 帮助
