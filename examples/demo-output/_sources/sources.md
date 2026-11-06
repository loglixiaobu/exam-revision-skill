# 提取来源（未经过视觉校对）

## S001 — 01-search.pdf

### [S001:p0001]

Algorithms: Searching (original synthetic course)
Linear search checks elements in order. Worst-case comparisons: n.
Example: [4, 1, 7, 3], target 7. Check 4, then 1, then 7: 3 comparisons.

### [S001:p0002]

Binary search requires a sorted ascending array.
Use inclusive indices low=0, high=n-1. mid=(low+high)//2.
If a[mid]<target: low=mid+1; if larger: high=mid-1; else return mid.
Stop when low>high: target is absent. Worst-case time O(log n).
Example: [1,3,5,7,9], target 7. mid=2 (5), then mid=3 (7).

## S002 — 02-boundaries.docx

### [S002:b0001]

算法补充：复杂度与边界

### [S002:b0002]

大O描述增长阶而不是实际运行秒数。同一输入规模下，常数和实现仍会影响速度。

### [S002:b0003]

边界情况

### [S002:b0004]

空数组：high=-1，循环不进入，返回未找到。重复元素：普通二分查找返回某个匹配位置，不能保证是第一个。

### [S002:b0005]

算法 | 前提
二分查找 | 数组有序

### [S002:b0006]

例题：在[2,2,2]中查找2，初始mid=1，因此返回下标1，不是首个位置。
