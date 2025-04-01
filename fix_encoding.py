#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
修复配置文件编码问题

此脚本用于修复Windows下配置文件的编码问题
将config.ini转换为UTF-8编码
"""

import os
import sys
import argparse
import shutil
import codecs

def fix_config_encoding(config_file, backup=True):
    """
    修复配置文件的编码，转换为UTF-8
    
    Args:
        config_file: 配置文件路径
        backup: 是否创建备份
    """
    # 检查文件是否存在
    if not os.path.exists(config_file):
        print(f"错误: 文件 {config_file} 不存在")
        return False
    
    # 创建备份
    if backup:
        backup_file = f"{config_file}.bak"
        try:
            shutil.copy2(config_file, backup_file)
            print(f"已创建备份文件: {backup_file}")
        except Exception as e:
            print(f"创建备份时出错: {str(e)}")
            return False
    
    # 尝试使用不同编码读取文件内容
    content = None
    encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    
    for encoding in encodings:
        try:
            with codecs.open(config_file, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"成功使用 {encoding} 编码读取文件")
                break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"读取文件时出错: {str(e)}")
            return False
    
    if content is None:
        print("错误: 无法使用已知编码读取文件")
        return False
    
    # 以UTF-8编码写回文件
    try:
        with codecs.open(config_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"成功将文件转换为UTF-8编码: {config_file}")
        return True
    except Exception as e:
        print(f"写入文件时出错: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='修复配置文件编码问题')
    parser.add_argument('config_file', help='配置文件路径', nargs='?', default='config.ini')
    parser.add_argument('--no-backup', action='store_true', help='不创建备份文件')
    
    args = parser.parse_args()
    
    if fix_config_encoding(args.config_file, not args.no_backup):
        print("编码修复完成，现在可以正常使用配置文件了")
    else:
        print("编码修复失败")
        sys.exit(1)

if __name__ == '__main__':
    main() 