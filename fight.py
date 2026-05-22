T=int(input())
for i in range(T):
    n=int(input())
    r=[0,0,0]
    b=[0,0,0]
    aid=[3,1,3]
    flag=True
    for j in range(n):
        name, type = input().split()
        if not flag:
            continue
        index=int(type)-1
        if name == 'R' and b[index]<aid[index]:
            r[index] += 1
        elif name=='B' and r[index]<aid[index]:
            b[index] += 1
        if flag and ((r[0] >= 3 and r[1] >= 1) or (r[0] >= 3 and r[2] >= 3) or (r[1] >= 1 and r[2] >= 3)):
            print('R')
            flag=False
        if flag and ((b[0] >= 3 and b[1] >= 1) or (b[0] >= 3 and b[2] >= 3) or (b[1] >= 1 and b[2] >= 3)):
            print('B')
            flag=False
    if flag:
        print('None')