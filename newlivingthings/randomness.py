# randomness.py
import os

def true_random_byte():
    """返回一个 0~255 的真随机整数（来自操作系统熵池）"""
    return os.urandom(1)[0]

def true_random_int(min_val, max_val):
    """返回 [min_val, max_val] 范围内的真随机整数"""
    if min_val == max_val:
        return min_val
    raw = true_random_byte()
    return min_val + (raw % (max_val - min_val + 1))

def true_random_bool(prob_true=0.5):
    """返回一个真随机布尔值，prob_true 为真的概率（近似）"""
    return (true_random_byte() / 255.0) < prob_true