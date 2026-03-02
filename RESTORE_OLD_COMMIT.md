# 恢复被 force push 覆盖前的版本（commit 080afd0）

你找到的 commit **080afd0**（Alpha 2.2）在 GitHub 上还在，只是不再属于任何分支。按下面任选一种方式即可把旧代码拉回本地或恢复成分支。

---

## 方法一：在 GitHub 上从该 commit 新建分支（推荐）

1. **用 GitHub API 新建分支**（需要 Personal Access Token，权限勾选 `repo`）  
   在终端执行（把 `YOUR_GITHUB_TOKEN` 换成你的 token）：

   ```bash
   curl -X POST \
     -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     https://api.github.com/repos/Bailuer/NovelMotion/git/refs \
     -d '{"ref":"refs/heads/old-alpha","sha":"080afd0"}'
   ```

2. **本地拉取并切换到这个分支**：

   ```bash
   cd /Users/shuo/Documents/NovelMotion
   git fetch origin old-alpha
   git checkout old-alpha
   ```

   这样你当前目录就是旧版（novelmotion 包、GUI、sd_renderer、角色卡等）。  
   想回到现在的精简版时执行：`git checkout main`。

---

## 方法二：浏览器下载该 commit 的 ZIP

1. 在浏览器打开（用完整 SHA）：  
   **https://github.com/Bailuer/NovelMotion/archive/080afd0.zip**

2. 若可以下载，解压后会得到类似 `NovelMotion-080afd0` 的文件夹，即该 commit 的完整快照。

3. 若只想参考或拷贝部分文件，直接在该文件夹里复制即可；若希望变成仓库里的一个分支，可以在本仓库里把该 commit 拉成分支（先完成方法一），或把解压后的内容拷到当前仓库再单独建分支提交。

---

## 方法三：在 GitHub 网页上找 “Restore” / “Create branch”

1. 打开：https://github.com/Bailuer/NovelMotion/commit/080afd0  
2. 看页面上是否有 **“Restore branch”** 或 **“Create branch from this commit”** 等按钮，有的话点一下即可在 GitHub 上从 080afd0 建一个新分支。  
3. 建好后在本地执行：

   ```bash
   git fetch origin
   git checkout <刚创建的分支名>
   ```

---

## 两个版本的关系

| 分支/版本 | 内容 |
|----------|------|
| **main**（当前） | 精简 MVP：单文件 `main.py` + README，无 key，适合公开。 |
| **080afd0 / old-alpha**（旧版） | 完整工具链：`novelmotion/` 包、`novelmotion_ui.py`、`sd_renderer.py`、角色卡、LLM、GUI、outputs 等。 |

恢复后建议把旧版保留在分支 `old-alpha`，`main` 继续做公开用；需要时在两个分支之间切换即可。
