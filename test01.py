T = int(input())

need = [3, 1, 3]

for _ in range(T):
    n = int(input())

    r = [0, 0, 0]
    b = [0, 0, 0]
    owner = [0, 0, 0]   # 0=没人完成，1=R完成，2=B完成

    ans = "None"

    for _ in range(n):
        team, tp = input().split()
        tp = int(tp) - 1

        # 已经分出胜负，后续输入只读不算
        if ans != "None":
            continue

        # 该目标已被完成，后续事件无效
        if owner[tp] != 0:
            continue

        if team == 'R':
            r[tp] += 1
            if r[tp] == need[tp]:
                owner[tp] = 1
        else:
            b[tp] += 1
            if b[tp] == need[tp]:
                owner[tp] = 2

        # 统计目标归属数
        rcnt = owner.count(1)
        bcnt = owner.count(2)

        if rcnt >= 2:
            ans = "R"
        elif bcnt >= 2:
            ans = "B"

    print(ans)