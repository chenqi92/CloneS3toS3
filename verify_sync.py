#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
校验源桶和目标桶的对象数量与一致性。

使用修复后的显式分页 + v1 回退，分别列出源端和目标端所有对象，
对比差异，输出缺失/大小不一致的 key 到文件。

用法:
    python verify_sync.py --config config.ini --buckets algorithm
    python verify_sync.py --config config.ini --buckets algorithm,cameratest
"""

import argparse
import logging
import sys
from typing import Dict, List, Optional

import boto3

from main import load_config, retry_operation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def list_all_objects(client, bucket_name: str) -> Dict[str, int]:
    """
    使用显式分页 + v1 回退列出桶中所有对象，返回 {key: size}。
    """
    objects: Dict[str, int] = {}
    continuation_token: Optional[str] = None
    page_count = 0

    while True:
        kwargs = {'Bucket': bucket_name, 'MaxKeys': 1000}
        if continuation_token:
            kwargs['ContinuationToken'] = continuation_token

        response = retry_operation(client.list_objects_v2, **kwargs)
        page_count += 1
        contents = response.get('Contents', []) or []
        for obj in contents:
            objects[obj['Key']] = obj['Size']

        if not response.get('IsTruncated', False):
            break

        next_token = response.get('NextContinuationToken')
        if not next_token:
            logger.warning(
                f"桶 {bucket_name} v2 分页第 {page_count} 页缺少 NextContinuationToken，"
                f"已列 {len(objects)} 个对象，回退到 v1"
            )
            last_key = contents[-1]['Key'] if contents else None
            v1_objs = _list_v1(client, bucket_name, start_marker=last_key)
            objects.update(v1_objs)
            break

        continuation_token = next_token

    logger.info(f"桶 {bucket_name} 通过 {page_count} 页 v2 共列出 {len(objects)} 个对象")
    return objects


def _list_v1(client, bucket_name: str, start_marker: Optional[str] = None) -> Dict[str, int]:
    objects: Dict[str, int] = {}
    marker = start_marker
    page_count = 0

    while True:
        kwargs = {'Bucket': bucket_name, 'MaxKeys': 1000}
        if marker:
            kwargs['Marker'] = marker

        response = retry_operation(client.list_objects, **kwargs)
        page_count += 1
        contents = response.get('Contents', []) or []
        for obj in contents:
            objects[obj['Key']] = obj['Size']

        if not response.get('IsTruncated', False):
            break

        next_marker = response.get('NextMarker')
        if not next_marker and contents:
            next_marker = contents[-1]['Key']
        if not next_marker or next_marker == marker:
            logger.error(f"桶 {bucket_name} v1 marker 无法推进，终止")
            break
        marker = next_marker

    logger.info(f"桶 {bucket_name} v1 补齐 {page_count} 页，共 {len(objects)} 个对象")
    return objects


def format_size(size_bytes: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"


def compare_bucket(source_client, target_client, bucket_name: str) -> bool:
    logger.info(f"===== 校验桶: {bucket_name} =====")

    src = list_all_objects(source_client, bucket_name)
    dst = list_all_objects(target_client, bucket_name)

    src_count, src_size = len(src), sum(src.values())
    dst_count, dst_size = len(dst), sum(dst.values())

    logger.info(f"源:   {src_count} 个对象, {format_size(src_size)}")
    logger.info(f"目标: {dst_count} 个对象, {format_size(dst_size)}")

    missing = [k for k in src if k not in dst]
    size_mismatch = [k for k in src if k in dst and dst[k] != src[k]]
    extra = [k for k in dst if k not in src]

    logger.info(f"目标缺失:   {len(missing)}")
    logger.info(f"大小不一致: {len(size_mismatch)}")
    logger.info(f"目标多余:   {len(extra)}")

    if missing:
        out = f"missing_{bucket_name}.txt"
        with open(out, 'w', encoding='utf-8') as f:
            for k in missing:
                f.write(k + '\n')
        logger.info(f"已写入缺失key列表: {out}")

    if size_mismatch:
        out = f"size_mismatch_{bucket_name}.txt"
        with open(out, 'w', encoding='utf-8') as f:
            for k in size_mismatch:
                f.write(f"{k}\tsrc={src[k]}\tdst={dst[k]}\n")
        logger.info(f"已写入大小不一致key列表: {out}")

    ok = not missing and not size_mismatch
    logger.info(f"桶 {bucket_name} 一致性: {'OK' if ok else '不一致'}")
    return ok


def main():
    parser = argparse.ArgumentParser(description='校验源/目标 S3 桶一致性')
    parser.add_argument('--config', required=True, help='配置文件路径')
    parser.add_argument('--buckets', help='要校验的桶，逗号分隔 (默认使用配置文件中的列表)')
    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        sys.exit(1)

    buckets: List[str] = (
        [b.strip() for b in args.buckets.split(',') if b.strip()]
        if args.buckets else config['buckets']
    )

    source_client = boto3.client(
        's3',
        endpoint_url=config['source_endpoint'],
        aws_access_key_id=config['source_access_key'],
        aws_secret_access_key=config['source_secret_key'],
        config=boto3.session.Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
    )
    target_client = boto3.client(
        's3',
        endpoint_url=config['target_endpoint'],
        aws_access_key_id=config['target_access_key'],
        aws_secret_access_key=config['target_secret_key']
    )

    all_ok = True
    for bucket in buckets:
        try:
            if not compare_bucket(source_client, target_client, bucket):
                all_ok = False
        except Exception as e:
            logger.error(f"校验桶 {bucket} 时出错: {e}")
            all_ok = False

    sys.exit(0 if all_ok else 2)


if __name__ == '__main__':
    main()
