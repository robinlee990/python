def morse_code_decryption(txt):
    #.--. . .--.   -.... ----. ...--   –   .--. -.-- - .... --- -.   ...-- .-.-.- .---- ..---   .-. . .-.. . .- ... .   ... -.-. .... . -.. ..- .-.. .
    """接收密文字符串为参数，返回用摩斯密码解密后的字符串。"""
    char = 'abcdefghijklmnopqrstuvwxyz' + '0123456789' + '.:,;?=\'/!-_"()$&@ '
    morse_letter = [".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---", "-.-", ".-..", "--", "-.",
                    "---", ".--.", "--.-", ".-.", "...", "-", "..-", "...-", ".--", "-..-", "-.--", "--.."]
    morse_digit = ['-----', '.----', '..---', '...--', '....-', '.....', '-....', '--...', '---..', '----.']
    morse_spec = ['.-.-.-', '---...', '--..--', '-.-.-.', '..- -..', '-...-', '.----.', '-..-.', '-.-.--', '-....-',
                  '..--.-', '.-..-.', '-.--.', '-.--.-', '...-..-', '·-···', '.--.-.', '']
    txt = txt.lower()
    all_morse = morse_letter + morse_digit + morse_spec
    # 构建反向字典：电码 -> 字符
    morse_dict = {code: char for code, char in zip(all_morse, char)}
    print(morse_dict)

    codes = txt.split(' ')
    print(codes)
    decodes = []
    count = 0
    for code in codes:
        if code=='':
            count += 1
            if count == 2:
                decodes.append(' ')
            continue
        if code in all_morse:
            count = 0
            decodes.append(morse_dict[code])
        else:
            count=0
            decodes.append(code)
    print(decodes)
    s = ''
    for x in decodes:
        s += x
    return s


if __name__ == '__main__':
    ciphertext = input()  # 输入一个密文
    print(morse_code_decryption(ciphertext))  # 调用函数，并输出返回值