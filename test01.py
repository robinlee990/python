def f(n):
    s=''
    while n>0:
        s=str(n%2)+s
        n//=2
    return s
def f1(s):
    res=s[0]
    for i in range(1,len(s)):
        k=int(s[i])^int(s[i-1])
        res=res+str(k)
    return res

n=int(input())
for i in range(2**n):
    s=f(i).zfill(n)
    res=f1(s)
    print(res)