#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
按条件删除源端 S3 对象。

默认行为是 dry-run，只列出将要删除的对象和预估释放空间，不真正删除。
只有加上 --execute 才会调用删除。

示例:
    python delete_source_objects.py --config config.ini --bucket algorithm --prefix tmp/
    python delete_source_objects.py --config config.ini --bucket algorithm --older-than-days 30 --max-objects 500
    python delete_source_objects.py --config config.ini --bucket algorithm --prefix upload/tmp/ --execute
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from main import load_config, retry_operation


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_arguments():
    parser = argparse.ArgumentParser(description='按条件删除源端 S3 对象（默认 dry-run）')
    parser.add_argument('--config', required=True, help='配置文件路径')
    parser.add_argument('--bucket', required=True, help='要删除的源端桶名')
    parser.add_argument('--prefix', default='', help='仅删除指定前缀下的对象')
    parser.add_argument('--older-than-days', type=int, help='仅删除早于 N 天前的对象')
    parser.add_argument('--before-date', help='仅删除早于该日期的对象，格式 YYYY-MM-DD')
    parser.add_argument('--max-objects', type=int, help='最多删除多少个对象')
    parser.add_argument('--sample', type=int, default=20, help='dry-run 时最多展示多少个示例对象')
    parser.add_argument('--execute', action='store_true', help='实际执行删除；默认仅预览')
    parser.add_argument('--yes', action='store_true', help='执行删除时跳过二次确认提示')
    return parser.parse_args()


def create_source_client(config: Dict):
    return boto3.client(
        's3',
        endpoint_url=config['source_endpoint'],
        aws_access_key_id=config['source_access_key'],
        aws_secret_access_key=config['source_secret_key'],
        config=boto3.session.Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
    )


def list_all_objects(client, bucket_name: str, prefix: str = "") -> List[Dict]:
    """
    使用显式分页 + v1 回退列出桶中的对象。
    返回的对象至少包含 Key / Size / LastModified。
    """
    objects_by_key: Dict[str, Dict] = {}
    continuation_token: Optional[str] = None
    page_count = 0

    while True:
        kwargs = {'Bucket': bucket_name, 'MaxKeys': 1000}
        if prefix:
            kwargs['Prefix'] = prefix
        if continuation_token:
            kwargs['ContinuationToken'] = continuation_token

        response = retry_operation(client.list_objects_v2, **kwargs)
        page_count += 1
        contents = response.get('Contents', []) or []
        for obj in contents:
            objects_by_key[obj['Key']] = obj

        if not response.get('IsTruncated', False):
            break

        next_token = response.get('NextContinuationToken')
        if not next_token or next_token == continuation_token:
            logger.warning(
                f"桶 {bucket_name} list_objects_v2 分页异常，回退到 v1 分页继续列举"
            )
            last_key = contents[-1]['Key'] if contents else None
            v1_objects = list_objects_v1(client, bucket_name, prefix=prefix, start_marker=last_key)
            for obj in v1_objects:
                objects_by_key[obj['Key']] = obj
            break

        continuation_token = next_token

    logger.info(f"桶 {bucket_name} 共列出 {len(objects_by_key)} 个候选对象 ({page_count} 页 v2)")
    return list(objects_by_key.values())


def list_objects_v1(client, bucket_name: str, prefix: str = "", start_marker: Optional[str] = None) -> List[Dict]:
    objects_by_key: Dict[str, Dict] = {}
    marker = start_marker
    page_count = 0

    while True:
        kwargs = {'Bucket': bucket_name, 'MaxKeys': 1000}
        if prefix:
            kwargs['Prefix'] = prefix
        if marker:
            kwargs['Marker'] = marker

        response = retry_operation(client.list_objects, **kwargs)
        page_count += 1
        contents = response.get('Contents', []) or []
        for obj in contents:
            objects_by_key[obj['Key']] = obj

        if not response.get('IsTruncated', False):
            break

        next_marker = response.get('NextMarker')
        if not next_marker and contents:
            next_marker = contents[-1]['Key']
        if not next_marker or next_marker == marker:
            logger.error(f"桶 {bucket_name} v1 marker 无法推进，提前终止")
            break
        marker = next_marker

    logger.info(f"桶 {bucket_name} v1 回退共列出 {len(objects_by_key)} 个对象 ({page_count} 页)")
    return list(objects_by_key.values())


def parse_cutoff(args) -> Optional[datetime]:
    if args.older_than_days is not None and args.before_date:
        raise ValueError('--older-than-days 和 --before-date 只能使用一个')

    if args.older_than_days is not None:
        if args.older_than_days < 0:
            raise ValueError('--older-than-days 不能小于 0')
        return datetime.now(timezone.utc) - timedelta(days=args.older_than_days)

    if args.before_date:
        try:
            dt = datetime.strptime(args.before_date, '%Y-%m-%d')
            return dt.replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise ValueError('--before-date 格式必须是 YYYY-MM-DD') from e

    return None


def filter_objects(objects: List[Dict], cutoff: Optional[datetime]) -> List[Dict]:
    if cutoff is None:
        return objects
    return [obj for obj in objects if obj['LastModified'] < cutoff]


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def print_preview(objects: List[Dict], sample: int):
    logger.info("以下是候选删除对象示例:")
    for obj in objects[:sample]:
        last_modified = obj['LastModified'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        logger.info(f"  {obj['Key']} | {format_size(obj['Size'])} | {last_modified}")
    if len(objects) > sample:
        logger.info(f"  ... 其余 {len(objects) - sample} 个对象未展开")


def confirm_or_exit(args, total_objects: int, total_size: int):
    if not args.execute:
        logger.info("当前为 dry-run；如确认无误，请追加 --execute 真正删除")
        return False

    if args.yes:
        return True

    prompt = (
        f"确认删除源桶 {args.bucket} 中 {total_objects} 个对象，"
        f"预计释放 {format_size(total_size)}？输入 DELETE 确认: "
    )
    user_input = input(prompt).strip()
    if user_input != 'DELETE':
        logger.info("未确认，已取消删除")
        return False
    return True


def delete_objects(client, bucket_name: str, objects: List[Dict]) -> int:
    deleted = 0
    batch_size = 1000

    for start in range(0, len(objects), batch_size):
        batch = objects[start:start + batch_size]
        delete_payload = {'Objects': [{'Key': obj['Key']} for obj in batch], 'Quiet': False}

        response = retry_operation(
            client.delete_objects,
            Bucket=bucket_name,
            Delete=delete_payload
        )

        deleted += len(response.get('Deleted', []) or [])
        errors = response.get('Errors', []) or []
        for err in errors:
            logger.error(f"删除失败: {err.get('Key')} | {err.get('Code')} | {err.get('Message')}")

        logger.info(f"删除进度: {min(start + batch_size, len(objects))}/{len(objects)}")

    return deleted


def main():
    args = parse_arguments()

    try:
        cutoff = parse_cutoff(args)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(2)

    config = load_config(args.config)
    if not config:
        sys.exit(1)

    has_filter = bool(args.prefix or cutoff or args.max_objects)
    if args.execute and not has_filter:
        logger.error('执行删除时必须至少指定一个筛选条件: --prefix / --older-than-days / --before-date / --max-objects')
        sys.exit(2)

    client = create_source_client(config)

    try:
        retry_operation(client.head_bucket, Bucket=args.bucket)
    except ClientError as e:
        logger.error(f"无法访问源桶 {args.bucket}: {e.response.get('Error', {}).get('Code')} - {str(e)}")
        sys.exit(1)

    objects = list_all_objects(client, args.bucket, prefix=args.prefix)
    objects = filter_objects(objects, cutoff)
    objects.sort(key=lambda item: item['LastModified'])

    if args.max_objects is not None:
        if args.max_objects <= 0:
            logger.error('--max-objects 必须大于 0')
            sys.exit(2)
        objects = objects[:args.max_objects]

    total_size = sum(obj['Size'] for obj in objects)
    logger.info(
        f"候选对象 {len(objects)} 个，预计可释放 {format_size(total_size)} "
        f"(bucket={args.bucket}, prefix={args.prefix or '<all>'})"
    )

    if not objects:
        logger.info("没有匹配到可删除对象")
        return

    print_preview(objects, max(1, args.sample))

    if not confirm_or_exit(args, len(objects), total_size):
        return

    deleted = delete_objects(client, args.bucket, objects)
    logger.info(f"删除完成，成功删除 {deleted}/{len(objects)} 个对象")


if __name__ == '__main__':
    main()
