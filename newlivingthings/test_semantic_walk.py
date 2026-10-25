# test_semantic_walk.py
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

seed_words = ["猫", "太阳", "思考", "窗台", "橘子"]
noise_levels = [0.05, 0.1, 0.15, 0.2, 0.3]
steps_range = [1, 2, 3, 5]

def find_nearest(vec, word_list):
    vecs = model.encode(word_list)
    sims = np.dot(vecs, vec) / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(vec) + 1e-8)
    return word_list[np.argmax(sims)]

# 从记忆库读取词表（这里硬编码示例）
word_list = ["猫", "太阳", "思考", "窗台", "橘子", "光", "温暖", "跳跃",
             "石头", "苹果", "花朵", "杯子", "云", "风", "雨", "雪", "狗", "鸟"]

print("参数测试：从'猫'出发，不同噪声和步数下的到达词")
print("=" * 60)
for noise in noise_levels:
    for steps in steps_range:
        vec = model.encode("猫")
        for _ in range(steps):
            vec = vec + np.random.normal(0, noise, vec.shape)
        nearest = find_nearest(vec, word_list)
        print(f"noise={noise:.2f}, steps={steps}: → {nearest}")
    print("-" * 40)