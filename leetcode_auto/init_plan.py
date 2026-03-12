"""首次运行时自动创建刷题计划文件夹和模板文件。"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))

SLUG_CATEGORY: dict[str, str] = {
    "two-sum": "哈希表", "add-two-numbers": "链表",
    "longest-substring-without-repeating-characters": "滑动窗口",
    "median-of-two-sorted-arrays": "二分查找",
    "longest-palindromic-substring": "动态规划",
    "container-with-most-water": "双指针", "3sum": "双指针",
    "letter-combinations-of-a-phone-number": "回溯",
    "remove-nth-node-from-end-of-list": "链表",
    "valid-parentheses": "栈", "merge-two-sorted-lists": "链表",
    "generate-parentheses": "回溯", "merge-k-sorted-lists": "链表",
    "swap-nodes-in-pairs": "链表", "reverse-nodes-in-k-group": "链表",
    "next-permutation": "数组", "longest-valid-parentheses": "栈",
    "search-in-rotated-sorted-array": "二分查找",
    "find-first-and-last-position-of-element-in-sorted-array": "二分查找",
    "combination-sum": "回溯", "first-missing-positive": "数组",
    "trapping-rain-water": "双指针", "permutations": "回溯",
    "rotate-image": "数组", "group-anagrams": "哈希表",
    "maximum-subarray": "动态规划", "jump-game": "贪心",
    "merge-intervals": "数组", "unique-paths": "动态规划",
    "minimum-path-sum": "动态规划", "climbing-stairs": "动态规划",
    "edit-distance": "动态规划", "sort-colors": "双指针",
    "minimum-window-substring": "滑动窗口", "subsets": "回溯",
    "word-search": "回溯", "largest-rectangle-in-histogram": "栈",
    "maximal-rectangle": "栈", "binary-tree-inorder-traversal": "二叉树",
    "unique-binary-search-trees": "动态规划",
    "validate-binary-search-tree": "二叉树", "symmetric-tree": "二叉树",
    "binary-tree-level-order-traversal": "二叉树",
    "maximum-depth-of-binary-tree": "二叉树",
    "construct-binary-tree-from-preorder-and-inorder-traversal": "二叉树",
    "flatten-binary-tree-to-linked-list": "二叉树",
    "best-time-to-buy-and-sell-stock": "动态规划",
    "binary-tree-maximum-path-sum": "二叉树",
    "longest-consecutive-sequence": "哈希表", "single-number": "位运算",
    "word-break": "动态规划", "linked-list-cycle": "链表",
    "linked-list-cycle-ii": "链表", "lru-cache": "设计",
    "sort-list": "链表", "maximum-product-subarray": "动态规划",
    "min-stack": "栈", "intersection-of-two-linked-lists": "链表",
    "majority-element": "数组", "house-robber": "动态规划",
    "number-of-islands": "图论", "reverse-linked-list": "链表",
    "course-schedule": "图论", "implement-trie-prefix-tree": "设计",
    "kth-largest-element-in-an-array": "堆",
    "maximal-square": "动态规划", "invert-binary-tree": "二叉树",
    "palindrome-linked-list": "链表",
    "lowest-common-ancestor-of-a-binary-tree": "二叉树",
    "product-of-array-except-self": "数组",
    "sliding-window-maximum": "栈", "search-a-2d-matrix-ii": "二分查找",
    "perfect-squares": "动态规划", "move-zeroes": "双指针",
    "find-the-duplicate-number": "双指针",
    "longest-increasing-subsequence": "动态规划",
    "remove-invalid-parentheses": "回溯",
    "best-time-to-buy-and-sell-stock-with-cooldown": "动态规划",
    "burst-balloons": "动态规划", "coin-change": "动态规划",
    "house-robber-iii": "二叉树", "counting-bits": "位运算",
    "top-k-frequent-elements": "堆", "decode-string": "栈",
    "evaluate-division": "图论",
    "queue-reconstruction-by-height": "贪心",
    "partition-equal-subset-sum": "动态规划",
    "path-sum-iii": "二叉树",
    "find-all-anagrams-in-a-string": "滑动窗口",
    "find-all-numbers-disappeared-in-an-array": "数组",
    "hamming-distance": "位运算", "target-sum": "动态规划",
    "convert-bst-to-greater-tree": "二叉树",
    "diameter-of-binary-tree": "二叉树",
    "subarray-sum-equals-k": "哈希表",
    "shortest-unsorted-continuous-subarray": "数组",
    "merge-two-binary-trees": "二叉树", "task-scheduler": "贪心",
    "palindromic-substrings": "动态规划", "daily-temperatures": "栈",
    "partition-labels": "贪心",
}

HOT100 = [
    (1, "两数之和", "two-sum", "简单"),
    (2, "两数相加", "add-two-numbers", "中等"),
    (3, "无重复字符的最长子串", "longest-substring-without-repeating-characters", "中等"),
    (4, "寻找两个正序数组的中位数", "median-of-two-sorted-arrays", "困难"),
    (5, "最长回文子串", "longest-palindromic-substring", "中等"),
    (11, "盛最多水的容器", "container-with-most-water", "中等"),
    (15, "三数之和", "3sum", "中等"),
    (17, "电话号码的字母组合", "letter-combinations-of-a-phone-number", "中等"),
    (19, "删除链表的倒数第N个结点", "remove-nth-node-from-end-of-list", "中等"),
    (20, "有效的括号", "valid-parentheses", "简单"),
    (21, "合并两个有序链表", "merge-two-sorted-lists", "简单"),
    (22, "括号生成", "generate-parentheses", "中等"),
    (23, "合并K个升序链表", "merge-k-sorted-lists", "困难"),
    (24, "两两交换链表中的节点", "swap-nodes-in-pairs", "中等"),
    (25, "K个一组翻转链表", "reverse-nodes-in-k-group", "困难"),
    (31, "下一个排列", "next-permutation", "中等"),
    (32, "最长有效括号", "longest-valid-parentheses", "困难"),
    (33, "搜索旋转排序数组", "search-in-rotated-sorted-array", "中等"),
    (34, "在排序数组中查找元素的第一个和最后一个位置", "find-first-and-last-position-of-element-in-sorted-array", "中等"),
    (39, "组合总和", "combination-sum", "中等"),
    (41, "缺失的第一个正数", "first-missing-positive", "困难"),
    (42, "接雨水", "trapping-rain-water", "困难"),
    (46, "全排列", "permutations", "中等"),
    (48, "旋转图像", "rotate-image", "中等"),
    (49, "字母异位词分组", "group-anagrams", "中等"),
    (53, "最大子数组和", "maximum-subarray", "中等"),
    (55, "跳跃游戏", "jump-game", "中等"),
    (56, "合并区间", "merge-intervals", "中等"),
    (62, "不同路径", "unique-paths", "中等"),
    (64, "最小路径和", "minimum-path-sum", "中等"),
    (70, "爬楼梯", "climbing-stairs", "简单"),
    (72, "编辑距离", "edit-distance", "中等"),
    (75, "颜色分类", "sort-colors", "中等"),
    (76, "最小覆盖子串", "minimum-window-substring", "困难"),
    (78, "子集", "subsets", "中等"),
    (79, "单词搜索", "word-search", "中等"),
    (84, "柱状图中最大的矩形", "largest-rectangle-in-histogram", "困难"),
    (85, "最大矩形", "maximal-rectangle", "困难"),
    (94, "二叉树的中序遍历", "binary-tree-inorder-traversal", "简单"),
    (96, "不同的二叉搜索树", "unique-binary-search-trees", "中等"),
    (98, "验证二叉搜索树", "validate-binary-search-tree", "中等"),
    (101, "对称二叉树", "symmetric-tree", "简单"),
    (102, "二叉树的层序遍历", "binary-tree-level-order-traversal", "中等"),
    (104, "二叉树的最大深度", "maximum-depth-of-binary-tree", "简单"),
    (105, "从前序与中序遍历序列构造二叉树", "construct-binary-tree-from-preorder-and-inorder-traversal", "中等"),
    (114, "二叉树展开为链表", "flatten-binary-tree-to-linked-list", "中等"),
    (121, "买卖股票的最佳时机", "best-time-to-buy-and-sell-stock", "简单"),
    (124, "二叉树中的最大路径和", "binary-tree-maximum-path-sum", "困难"),
    (128, "最长连续序列", "longest-consecutive-sequence", "中等"),
    (136, "只出现一次的数字", "single-number", "简单"),
    (139, "单词拆分", "word-break", "中等"),
    (141, "环形链表", "linked-list-cycle", "简单"),
    (142, "环形链表 II", "linked-list-cycle-ii", "中等"),
    (146, "LRU 缓存", "lru-cache", "中等"),
    (148, "排序链表", "sort-list", "中等"),
    (152, "乘积最大子数组", "maximum-product-subarray", "中等"),
    (155, "最小栈", "min-stack", "中等"),
    (160, "相交链表", "intersection-of-two-linked-lists", "简单"),
    (169, "多数元素", "majority-element", "简单"),
    (198, "打家劫舍", "house-robber", "中等"),
    (200, "岛屿数量", "number-of-islands", "中等"),
    (206, "反转链表", "reverse-linked-list", "简单"),
    (207, "课程表", "course-schedule", "中等"),
    (208, "实现 Trie (前缀树)", "implement-trie-prefix-tree", "中等"),
    (215, "数组中的第K个最大元素", "kth-largest-element-in-an-array", "中等"),
    (221, "最大正方形", "maximal-square", "中等"),
    (226, "翻转二叉树", "invert-binary-tree", "简单"),
    (234, "回文链表", "palindrome-linked-list", "简单"),
    (236, "二叉树的最近公共祖先", "lowest-common-ancestor-of-a-binary-tree", "中等"),
    (238, "除自身以外数组的乘积", "product-of-array-except-self", "中等"),
    (239, "滑动窗口最大值", "sliding-window-maximum", "困难"),
    (240, "搜索二维矩阵 II", "search-a-2d-matrix-ii", "中等"),
    (279, "完全平方数", "perfect-squares", "中等"),
    (283, "移动零", "move-zeroes", "简单"),
    (287, "寻找重复数", "find-the-duplicate-number", "中等"),
    (300, "最长递增子序列", "longest-increasing-subsequence", "中等"),
    (301, "删除无效的括号", "remove-invalid-parentheses", "困难"),
    (309, "最佳买卖股票时机含冷冻期", "best-time-to-buy-and-sell-stock-with-cooldown", "中等"),
    (312, "戳气球", "burst-balloons", "困难"),
    (322, "零钱兑换", "coin-change", "中等"),
    (337, "打家劫舍 III", "house-robber-iii", "中等"),
    (338, "比特位计数", "counting-bits", "简单"),
    (347, "前 K 个高频元素", "top-k-frequent-elements", "中等"),
    (394, "字符串解码", "decode-string", "中等"),
    (399, "除法求值", "evaluate-division", "中等"),
    (406, "根据身高重建队列", "queue-reconstruction-by-height", "中等"),
    (416, "分割等和子集", "partition-equal-subset-sum", "中等"),
    (437, "路径总和 III", "path-sum-iii", "中等"),
    (438, "找到字符串中所有字母异位词", "find-all-anagrams-in-a-string", "中等"),
    (448, "找到所有数组中消失的数字", "find-all-numbers-disappeared-in-an-array", "简单"),
    (461, "汉明距离", "hamming-distance", "简单"),
    (494, "目标和", "target-sum", "中等"),
    (538, "把二叉搜索树转换为累加树", "convert-bst-to-greater-tree", "中等"),
    (543, "二叉树的直径", "diameter-of-binary-tree", "简单"),
    (560, "和为 K 的子数组", "subarray-sum-equals-k", "中等"),
    (581, "最短无序连续子数组", "shortest-unsorted-continuous-subarray", "中等"),
    (617, "合并二叉树", "merge-two-binary-trees", "简单"),
    (621, "任务调度器", "task-scheduler", "中等"),
    (647, "回文子串", "palindromic-substrings", "中等"),
    (739, "每日温度", "daily-temperatures", "中等"),
    (763, "划分字母区间", "partition-labels", "中等"),
]


def _gen_progress_table() -> str:
    lines = [
        "# 刷题进度表\n",
        "\n",
        "| 序号 | 题目 | 难度 | R1 | R2 | R3 | R4 | R5 | 状态 | 最后完成日期 |\n",
        "| ---: | --- | --- | :---: | :---: | :---: | :---: | :---: | --- | --- |\n",
    ]
    for idx, (num, name, slug, diff) in enumerate(HOT100, 1):
        link = f"[{num}. {name}](https://leetcode.cn/problems/{slug}/)"
        lines.append(
            f"| {idx} | {link} | {diff} |   |   |   |   |   |   | — |\n"
        )
    return "".join(lines)


def _gen_checkin(today_str: str) -> str:
    return (
        f"# 每日打卡\n"
        f"\n"
        f"## {today_str}（Day 1）\n"
        f"- 新题完成：\n"
        f"- 复习完成：\n"
        f"- 今日总时长：\n"
        f"- 卡点题目：\n"
        f"- 明日计划：\n"
        f"\n"
        f"---\n"
        f"\n"
        f"> 使用方式：每天新增一个日期块，记录\"新题/复习/时长/卡点/明日计划\"。\n"
    )


def _gen_dashboard() -> str:
    total = len(HOT100)
    return (
        f"# Hot100 进度看板\n"
        f"\n"
        f"## 总览\n"
        f"- 题目总数：{total}\n"
        f"- 总轮次数：{total * 5}（{total}×5）\n"
        f"- 已完成轮次：0\n"
        f"- 今日完成轮次：0\n"
        f"- 完成率：0%\n"
        f"\n"
        f"## 今日待办（建议）\n"
        f"- 新题 5 道（从进度表中 R1 为空的题开始）\n"
        f"- 复习 10 道（优先 R1 完成且到期复习的题）\n"
        f"\n"
        f"## 本周目标\n"
        f"- 完成 R1 前 35 题\n"
        f"- 建立稳定打卡节奏（至少 6/7 天）\n"
        f"\n"
        f"> 此看板由 leetcode 命令自动更新。\n"
    )


def _gen_master_plan(today_str: str) -> str:
    return (
        f"# LeetCode Hot100 刷题总计划（每题 5 遍）\n"
        f"\n"
        f"## 目标\n"
        f"- 题单：LeetCode Hot100\n"
        f"- 轮次：每题完成 5 遍（R1~R5）\n"
        f"- 启动日期：{today_str}\n"
        f"\n"
        f"## 执行规则\n"
        f"1. 每天先做新题，再做复习题。\n"
        f"2. 每道题每做完一遍，就在进度表里对应轮次填日期。\n"
        f"3. 若某题做错或超时，标记为\"需复盘\"，当天加做一次题解复述。\n"
        f"4. 每天结束更新：\n"
        f"   - `02_每日打卡.md`\n"
        f"   - `03_进度看板.md`\n"
        f"\n"
        f"## 每日建议节奏（可改）\n"
        f"- 新题：5 题/天\n"
        f"- 复习：10 题/天（按间隔回顾）\n"
        f"- 总时长：2~3 小时\n"
        f"\n"
        f"## 复习间隔建议\n"
        f"- R1：首次做题\n"
        f"- R2：+1 天\n"
        f"- R3：+3 天\n"
        f"- R4：+7 天\n"
        f"- R5：+14 天\n"
        f"\n"
        f"## 完成判定\n"
        f"- {len(HOT100)} 题 × 5 轮 = {len(HOT100) * 5} 次完成记录\n"
        f"- 所有题目 R1~R5 均有日期，即本计划完成\n"
    )


def ensure_plan_files(plan_dir: Path, progress_file: Path,
                      checkin_file: Path, dashboard_file: Path):
    """检查刷题计划文件是否存在，缺失则自动创建。"""
    today_str = datetime.now(CST).strftime("%Y-%m-%d")
    created = []

    plan_dir.mkdir(parents=True, exist_ok=True)

    master_file = plan_dir / "00_总计划.md"
    if not master_file.exists():
        master_file.write_text(_gen_master_plan(today_str), encoding="utf-8")
        created.append(master_file.name)

    if not progress_file.exists():
        progress_file.write_text(_gen_progress_table(), encoding="utf-8")
        created.append(progress_file.name)

    if not checkin_file.exists():
        checkin_file.write_text(_gen_checkin(today_str), encoding="utf-8")
        created.append(checkin_file.name)

    if not dashboard_file.exists():
        dashboard_file.write_text(_gen_dashboard(), encoding="utf-8")
        created.append(dashboard_file.name)

    if created:
        print(f"已自动创建刷题计划文件：{', '.join(created)}")
        print(f"文件夹：{plan_dir}\n")
