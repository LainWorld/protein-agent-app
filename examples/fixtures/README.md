# Mock 示例坐标：RCSB PDB 1UBQ

[1ubq.pdb](1ubq.pdb) 是 2026-11-19 从 [RCSB 官方 PDB 文件服务](https://files.rcsb.org/download/1UBQ.pdb) 获取的原始文件：78,570 字节，SHA-256 `d4a6812d8951cf6594e6a0763f089e35f5a80b62acb3c117b2c5565228a7b161`。应用运行时读本地副本，不依赖 RCSB 在线。坐标文件属于 PDB 档案数据，见 [RCSB 使用政策](https://www.rcsb.org/pages/policies)。

来源：[1UBQ 条目](https://www.rcsb.org/structure/1UBQ)，Vijay-Kumar、Bugg 和 Cook，X 射线衍射，1.80 Å；[原始论文](https://doi.org/10.1016/0022-2836(87)90679-6)。链 A 为 76 aa 泛素：

```text
MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG
```

ESMFold2 Mock 和 Protenix Mock **都复制同一组实验坐标**，与提交序列无关。每个输出在 HEADER 后增加三行 REMARK 950，标明 Mock、来源、模型路线和任务 UUID；没有修改坐标。即使输入正好也是 1UBQ 的序列，结果仍然是示例，不是本次输入的真实预测。
