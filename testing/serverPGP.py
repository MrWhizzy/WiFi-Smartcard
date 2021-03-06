"""
serverPGP.py    22/07/2017

AUTHOR

    Christos Melas
    chr.melas@gmail.com

SYNOPSIS

    serverPGP.py

DESCRIPTION

    This is a Python implementation of a server that
    the ESP32 can connect to and perform all of its 
    supported functions.
"""
import sys
import time
import base64
import threading
import SocketServer
from getpass import getpass
from Crypto.Hash import SHA
from Crypto.PublicKey import RSA
from socket import error as SocketError


def sendAndGetResponse(cmd):
    global command      # The command APDU
    global response     # The response APDU
    global condCommand  # Condition to wait until a new APDU command arrives
    global condResponse # Condition to wait until a response is available
    global newCommand   # Flag for the handler that there is a new command
    global processing   # Flag for the run function that the processing has finished
    global err          # Flag for the run function that an error happened

    cmdBytes = bytearray.fromhex(cmd)
    with condCommand:
        command = cmdBytes
        newCommand = 1
        processing = 1
        condCommand.notify()

    with condResponse:
        while (processing == 1):
            condResponse.wait(0)

        resp = ''.join(["%02X "%ord(x) for x in response]).strip()
        if (err == 0):
            return resp
        else:               # ESP32 was probably disconnected
            sys.exit()      # Terminate execution


def checkResp(resp):
    respLen = len(resp)
    if (resp[respLen-5] == "6" and resp[respLen-4] == "1"):
        return resp[respLen-2] + resp[respLen-1] + " "
    else:
        return "00 "


def sendCommand(cmd):
    resp = sendAndGetResponse(cmd)
    while True:
        more = checkResp(resp)
        if (more == "00 "):
            return resp

        resp = resp[:len(resp)-6] + " " + sendAndGetResponse("00 C0 00 00 " + more)


def getLen(argStr):
    tmpLen = len(argStr)/3
    if (tmpLen < 128):
        return '{0:02X}'.format(int(tmpLen)) + " "
    elif (tmpLen < 256):
        return '81 {0:02X}'.format(int(tmpLen)) + " "
    else:
        longLen = '{0:04X}'.format(int(tmpLen))
        return "82 " + " ".join(longLen[i:i+2] for i in range(0, len(longLen), 2)) + " "


def getKeyTag(key):
    if (key == 1):
        return "B6 "
    elif (key == 2):
        return "B8 "
    elif (key == 3):
        return "A4 "
    else:
        return "00 "


def getFPTag(key):
    if (key == 1):
        return "C7 "
    elif (key == 2):
        return "C8 "
    elif (key == 3):
        return "C9 "
    else:
        return "00 "


def getTimeTag(key):
    if (key == 1):
        return "CE "
    elif (key == 2):
        return "CF "
    elif (key == 3):
        return "D0 "
    else:
        return "00 "


def promptForPass(mesg):
    while True:
        pw = getpass(mesg+" or 0 to cancel: ")
        if (pw == "0"):
            return 0
        return pw


def promptForKeyType():
    keyType = -1
    while True:
        print "\nPlease enter the type of the key:"
        print "\t(1) Signature\n\t(2) Decryption\n\t(3) Authentication\n\t(0) Back"
        try:
            keyType = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (0 <= keyType < 4):
            return keyType


def verify(p2):
    pw1 = promptForPass("Please enter the password")
    if (pw1 == 0):
        return False

    pw = " ".join("{:02x}".format(ord(c)) for c in pw1) + " "
    command = "00 20 00 " + p2 + '{0:02X}'.format(int(len(pw)/3)) + " " + pw
    if (sendCommand(command) == "90 00"):
        print "\nSuccessfully verified"
        return True
    else:
        print "\nVerification failed"
        getPWBytes()
        return False


def verifySelect():
    print "\n\t(1) VERIFY"

    select = -1
    while True:
        print "Please enter the type of PIN you would like to verify:"
        print "\t(1) PW1 (mode 81) for PSO:CDS"
        print "\t(2) PW1 (mode 82) for other commands"
        print "\t(3) PW3 (mode 83)"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        inval = False
        if (select == 0):
            return
        else:
            if (select == 1):
                p2 = "81 "              # VERIFY - PW1 81
            elif (select == 2):
                p2 = "82 "              # VERIFY - PW1 82
            elif (select == 3):
                p2 = "83 "              # VERIFY - PW3
            else:
                print "Invalid option\n"
                inval = True

            if (not (inval)):
                verify(p2)
            select = -1


def changeReferenceData():
    select = -1
    print "\n\t(2) CHANGE REFERENCE DATA"
    while True:
        print "Please select the password you would like to change:"
        print "\t(1) Change PW1"
        print "\t(2) Change PW3"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            return
        elif (select == 1):
            pw = promptForPass("Please enter the current PW1 password")
            if (pw == 0):
                return False

            mode = "81 "
            break
        elif (select == 2):
            pw = promptForPass("Please enter the current PW3 password")
            if (pw == 0):
                return False

            mode = "83 "
            break
        else:
            print "Invalid option\n"
        select = -1

    newPW = promptForPass("Please enter the new password")
    if (pw == 0):
        return False

    pwStr = " ".join("{:02x}".format(ord(c)) for c in pw) + " "
    newStr = " ".join("{:02x}".format(ord(c)) for c in newPW) + " "
    data = pwStr + newStr
    command = "00 24 00 " + mode + '{0:02X}'.format(int(len(data)/3)) + " " + data
    if (sendCommand(command) == "90 00"):
        print "\nOperation completed successfully\n"
        return True
    else:
        print "\nOperation failed"
        getPWBytes()
        return False


def resetRetryCounter():
    select = -1
    print "\n\t(3) RESET RETRY COUNTER"
    while True:
        print "Please select the way you would like to verify:"
        print "\t(1) Using the Resetting Code (RC)"
        print "\t(2) Using PW3"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            return
        elif (select == 1):
            pw = promptForPass("Please enter the resetting code (RC)")
            if (pw == 0):
                return False

            mode = "00 "
            break
        elif (select == 2):
            print "\nYou will need to verify the PW3 PIN"
            if (not (verify("83 "))):
                return False

            mode = "02 "
            break
        else:
            print "Invalid option\n"
        select = -1

    newPW = promptForPass("Please enter the new PW1 password")
    if (newPW == 0):
        return False

    newStr = " ".join("{:02x}".format(ord(c)) for c in newPW) + " "
    if (select == 1):
        pwStr = " ".join("{:02x}".format(ord(c)) for c in pw) + " "
        data = pwStr + newStr
    else:
        data = newStr

    command = "00 2C " + mode + "81 " + '{0:02X}'.format(int(len(data)/3)) + " " + data
    if (sendCommand(command) == "90 00"):
        print "\nOperation completed successfully\n"
        return True
    else:
        print "\nOperation failed"
        getPWBytes()
        return False


def performOperation(head):
    while True:
        print "Please select the way of input (max. 245 bytes):"
        print "\t(1) Import from file"
        print "\t(2) Enter via keyboard"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            break
        elif ((select != 1) and (select != 2)):
            print "Invalid option\n"
        else:
            if (select == 1):
                while True:
                    filename = raw_input("\nPlease enter the filename: ")
                    try:
                        f = open(filename, 'r')
                        inp = f.read()
                        if (len(inp) <= 245):
                            break
                        else:
                            print "Input must be <= 245 bytes"
                    except IOError:
                        print "No such file or directory"

                f.close()
            elif (select == 2):
                while True:
                    inp = raw_input("Input (max. 245 characters): ")
                    if (len(inp) <= 245):
                        break            

            inpS = " ".join("{:02x}".format(ord(c)) for c in inp) + " "
            command = head + '{0:02X}'.format(int(len(inpS)/3)) + " " + inpS
            return sendCommand(command)
        select = -1


def reverseOp(inp, filename, passwd):
        cip = ''.join(chr(x) for x in bytearray.fromhex(inp))
        f = open(filename, 'r')
        key = RSA.importKey(f.read(), passphrase = passwd)
        f.close()
        plain = key.encrypt(cip, "")
        plStr = ''.join(["%02X "%ord(x) for x in plain[0]]).strip()
        padding = plStr.find("FF 00 ") + 6
        print "Reverse Operation: " + plain[0][padding/3:] + "\n"


def computeDigSign():
    print "\nYou will need to verify the PW1 PIN"
    if (not (verify("81 "))):
        return False

    select = -1
    print "\n\tCompute Digital Signature"
    resp = performOperation("00 2A 9E 9A ")
    if (resp == "6A 88"):
        print "Signature key not found\n"
    elif (resp == "69 83"):
        print "\tOperation Blocked\n"
    else:
        print "Ciphertext: " + resp[:len(resp)-6] + "\n"
        reverseOp(resp[:len(resp)-6], "private.pem", "12345678")    # Temp hardcoded key


def sendChain(dataIn, INS):
    bytesSent = 0
    bytesToSend = len(dataIn)/3
    while (bytesToSend > 0):
        if (bytesToSend > 254):
            CLA = "10 "
            LC = "FE "
            tmpData = dataIn[bytesSent*3:(bytesSent+254)*3]
            bytesToSend = bytesToSend - 254
            bytesSent = bytesSent + 254
            apdu = CLA+INS+LC+tmpData
            sendCommand(apdu)
        else:
            CLA = "00 "
            LC = '{0:02X}'.format(bytesToSend) + " "
            tmpData = dataIn[bytesSent*3:]
            bytesToSend = 0
            apdu = CLA+INS+LC+tmpData
            return sendCommand(apdu)


def decipher():
    print "\nYou will need to verify the PW1 PIN"
    if (not (verify("82 "))):
        return False

    print "\n\tDecipher"
    while True:
        filename = raw_input("Please enter the filename (enter 0 to cancel): ")
        if (filename == "0"):
            return
        else: 
            try:
                f = open(filename, 'r')
                inp = f.read()
                f.close()
                break
            except IOError:
                print "No such file or directory"

    inpS = "00 " + " ".join("{:02x}".format(ord(c)) for c in inp).upper() + " "
    resp = sendChain(inpS, "2A 80 86 ")

    if (resp == "6A 88"):
        print "Decryption key not found\n"
    elif (resp == "69 83"):
        print "\tOperation Blocked\n"
    else:
        print "Decrypted: " + bytearray.fromhex(resp[:len(resp)-6]).decode() + "\n"


def performSecOp():
    select = -1
    print "\n\t(4) PERFORM SECURITY OPERATION"
    while True:
        print "Please select the security operation you would like to perform:"
        print "\t(1) Compute Digital Signature"
        print "\t(2) Decipher"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            return
        elif (select == 1):
            computeDigSign()
        elif (select == 2):
            decipher()
        else:
            print "Invalid option\n"
        select = -1


def intAuth():
    print "\nYou will need to verify the PW1 PIN"
    if (not (verify("82 "))):
        return False

    select = -1
    print "\n\t(5) INTERNAL AUTHENTICATE"
    resp = performOperation("00 88 00 00 ")
    if (resp == "6A 88"):
        print "Authentication key not found\n"
    elif (resp == "69 83"):
        print "\tOperation Blocked\n"
    else:
        print "Ciphertext: " + resp[:len(resp)-6] + "\n"
        reverseOp(resp[:len(resp)-6], "private.pem", "12345678")    # Temp hardcoded key



def putFP(data, keyType):       # Generate SHA1 fingerprint
    h = SHA.new()
    h.update(data)
    hStr = h.hexdigest().upper()
    fpStr = " ".join(hStr[i:i+2] for i in range(0, len(hStr), 2)) + " "
    tagFP = getFPTag(keyType)
    lenFP = getLen(fpStr)
    apdu = "00 DA 00 "+tagFP+lenFP+fpStr

    if (sendCommand(apdu) != "90 00"):
        return False

    return True


def putTime(keyType):           # Put the current timestamp
    timest = '{0:04X}'.format(int(time.time()))
    tsStr = " ".join(timest[i:i+2] for i in range(0, len(timest), 2)) + " "
    tagTime = getTimeTag(keyType)
    lenTS = getLen(tsStr)
    apdu = "00 DA 00 "+tagTime+lenTS+tsStr
    if (sendCommand(apdu) != "90 00"):
        return False

    return True


def genAsymKey():
    print "\nYou will need to verify the PW3 PIN"
    if (not (verify("83 "))):
        return False

    print "\n\t(6) GENERATE ASYMMETRIC KEY"
    keyType = promptForKeyType()
    if (keyType == 0):
        return False

    keyTag = getKeyTag(keyType)
    resp = sendCommand("00 47 80 00 02 " + keyTag + "00 00")
    pub = bytearray.fromhex(resp[9*3:265*3] + resp[267*3:270*3])

    if (not (putFP(pub, keyType))):
        return False

    if (not (putTime(keyType))):
        return False

    return True


def getChallenge():
    select = -1
    print "\n\t(7) GET CHALLENGE"
    length = getByteNumber("Please enter the length of the requested random number")

    if (length == 0):
        return
    else:
        command = "00 84 00 00 " + '{0:02X}'.format(length) + " "
        resp = sendCommand(command)
        print "\nResponse: "+ resp[:len(resp)-6] + "\n"


def getARD():
    resp = sendCommand("00 CA 00 6E 00") + " "    # GET DATA - Application Related Data
    if (resp[:5] == "69 85"):
        handleTerminated()
        return False

    tmpLen = int(resp[3]+resp[4], 16)
    offset = 2
    print "Application Related Data:\n\tApplication ID ...........: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 2

    tmpLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    print "\tHistorical Bytes .........: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 4

    tmpLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    print "\tExtended Capabilities ....: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 1

    tmpLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    print "\tAlgorithm Attributes\n\t\tSignature ........: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 1

    tmpLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    print "\t\tDecryption .......: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 1

    tmpLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    print "\t\tAuthentication ...: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + tmpLen + 2

    print "\tPW1 status bytes\n\t\tPW1 status .......: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tPW1 max length ...: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tRC max length ....: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tPW3 max length ...: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tPW1 remaining ....: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tRC remaining .....: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 1
    print "\t\tPW3 remaining ....: {}".format(int(resp[offset*3]+resp[offset*3+1], 16))
    offset = offset + 3

    tmpLen = 20
    print "\tKey Fingerprints\n\t\tSignature ........: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 20
    print "\t\tDecryption .......: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 20
    print "\t\tAuthentication ...: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 22

    tmpLen = 20
    print "\tCA Fingerprints\n\t\tCA 1 .............: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 20
    print "\t\tCA 2 .............: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 20
    print "\t\tCA 3 .............: " + resp[offset*3:(offset+tmpLen)*3]
    offset = offset + 22

    tmpLen = 4
    tStr = resp[offset*3]+resp[offset*3+1]+resp[offset*3+3]+resp[offset*3+4]
    tStr = tStr+resp[offset*3+6]+resp[offset*3+7]+resp[offset*3+9]+resp[offset*3+10]
    t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(tStr, 16)))
    print "\tKey Generation Times\n\t\tSignature: .......: " + t
    offset = offset + 4
    tStr = resp[offset*3]+resp[offset*3+1]+resp[offset*3+3]+resp[offset*3+4]
    tStr = tStr+resp[offset*3+6]+resp[offset*3+7]+resp[offset*3+9]+resp[offset*3+10]
    t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(tStr, 16)))
    print "\t\tDecryption: ......: " + t
    offset = offset + 4
    tStr = resp[offset*3]+resp[offset*3+1]+resp[offset*3+3]+resp[offset*3+4]
    tStr = tStr+resp[offset*3+6]+resp[offset*3+7]+resp[offset*3+9]+resp[offset*3+10]
    t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(tStr, 16)))
    print "\t\tAuthentication ...: " + t + "\n"
    return True


def getLoginData():
    resp = sendCommand("00 CA 00 5E 00") + " "    # GET DATA - Login Data
    print "\tLogin Data ...............: " + bytearray.fromhex(resp[:len(resp)-6]).decode()


def getURL():
    resp = sendCommand("00 CA 5F 50 00") + " "    # GET DATA - URL
    print "\tPublic Key URL ...........: " + bytearray.fromhex(resp[:len(resp)-6]).decode()


def getDSCnt():
    resp = sendCommand("00 CA 00 7A 00") + " "    # GET DATA - Security Support Template
    dsCnt = int(resp[6]+resp[7]+resp[9]+resp[10]+resp[12]+resp[13], 16)
    print "\tSignature Counter.........: {}\n".format(dsCnt)


def getCRD():
    resp = sendCommand("00 CA 00 65 00") + " "    # GET DATA - Cardholder Related Data
    nLen = int(resp[3]+resp[4], 16)
    offset = 2
    name = bytearray.fromhex(resp[offset*3:(offset+nLen)*3]).decode()
    print "Cardholder Related Data:\n\t\tName: ............: " + name
    offset = offset + nLen + 2

    lLen = int(resp[(offset*3)+1]+resp[(offset*3)+2], 16)
    offset = offset + 1
    lang = bytearray.fromhex(resp[offset*3:(offset+lLen)*3]).decode()
    print "\t\tLanguage prefs ...: " + lang
    offset = offset + lLen + 3

    if (resp[(offset*3)+1] == "1"):
        print "\t\tSex ..............: Male\n"
    elif (resp[(offset*3)+1] == "2"):
        print "\t\tSex ..............: Female\n"
    else:
        print "\t\tSex ..............: Not set\n"


def getPWBytes():
    resp = sendCommand("00 CA 00 C4 00") + "\n"    # GET DATA - PW Status Bytes
    print "\tPW1 tries remaining ......: {}".format(int(resp[12] + resp[13]))
    print "\tRC tries remaining .......: {}".format(int(resp[15] + resp[16]))
    print "\tPW3 tries remaining ......: {}".format(int(resp[18] + resp[19])) + "\n"


def getData():
    print "\n\t(8) GET DATA"

    select = -1
    while True:
        print "Please enter the type of data you would like to get:"
        print "\t(1) List all available data"
        print "\t(2) GET Cardholder Certificate"
        print "\t(3) GET PW Status Bytes"
        print "\t(4) GET Public Key"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            print ""
            return
        elif (select == 1):
            getARD()
            getLoginData()
            getURL()
            getDSCnt()
            getCRD()
        elif (select == 2):
            resp = sendCommand("00 CA 7F 21 00") + " "    # GET DATA - Cardholder Certificate
            print "Cardholder certificate (hex):\n" + resp[:len(resp)-6] + "\n"
        elif (select == 3):
            getPWBytes()                                           # GET DATA - PW Status Bytes
        elif (select == 4):
            keyType = promptForKeyType()
            if (keyType == 0):
                break

            keyTag = getKeyTag(keyType)
            resp = sendCommand("00 47 81 00 02 " + keyTag + "00 00")
            print "Modulus (hex): " + resp[9*3:265*3] + "\nExponent (hex): " + resp[267*3:270*3] + "\n"
        else:
            print "Invalid option\n"
        select = -1


def doPut(mesg, maxInp, tag):
    while True:
        inp = raw_input("\nPlease enter the " + mesg)
        if (len(inp) <= maxInp):
            break

    iStr = " ".join("{0:02x}".format(ord(c)) for c in inp).upper() + " "
    if (sendCommand("00 DA " + tag + getLen(iStr) + iStr) == "90 00"):
        print "Operation completed successfully\n"
    else:
        print "Operation failed\n"


def importKey():
    while True:
        filename = raw_input("\nPlease enter the private key filename (e.g. private.pem): ")
        try:
            f = open(filename, 'r')
            break
        except IOError:
            print "No such file or directory"

    while True:
        pw = getpass("Please enter the key password (optional): ")
        try:
            r = RSA.importKey(f.read(), passphrase = pw)
            f.close()
            break
        except ValueError:
            print "Wrong password"
            f.seek(0)

    e = '{0:06X}'.format(int(r.e))
    eStr = " ".join(e[i:i+2] for i in range(0, len(e), 2)) + " "

    p = '{0:0256X}'.format(int(r.p))
    pStr = " ".join(p[i:i+2] for i in range(0, len(p), 2)) + " "

    q = '{0:0256X}'.format(int(r.q))
    qStr = " ".join(q[i:i+2] for i in range(0, len(q), 2)) + " "

    pq = '{0:0256X}'.format(int(pow(r.q, r.p - 2, r.p)))
    pqStr = " ".join(pq[i:i+2] for i in range(0, len(pq), 2)) + " "

    dp = '{0:0256X}'.format(int(r.d % (r.p-1)))
    dpStr = " ".join(dp[i:i+2] for i in range(0, len(dp), 2)) + " "

    dq = '{0:0256X}'.format(int(r.d % (r.q-1)))
    dqStr = " ".join(dq[i:i+2] for i in range(0, len(dq), 2)) + " "

    n = '{0:0512X}'.format(int(r.n))
    nStr = " ".join(n[i:i+2] for i in range(0, len(n), 2)) + " "

    full = eStr + pStr + qStr + pqStr + dpStr + dqStr + nStr

    lenE = "91 " + getLen(eStr)
    lenP = "92 " + getLen(pStr)
    lenQ = "93 " + getLen(qStr)
    lenPQ = "94 " + getLen(pqStr)
    lenDP = "95 " + getLen(dpStr)
    lenDQ = "96 " + getLen(dqStr)
    lenN = "97 " + getLen(nStr)
    lenFull = "5F 48 " + getLen(full)

    TAG = "4D "
    keyType = promptForKeyType()
    if (keyType == 0):
        return False

    keyTag = getKeyTag(keyType)
    lenStr = lenE+lenP+lenQ+lenPQ+lenDP+lenDQ+lenN
    offset = "00 7F 48 " + getLen(lenStr)
    lenAll = getLen(keyTag+offset+lenStr+lenFull+full)
    data = (TAG+lenAll+keyTag+offset+lenStr+lenFull+full)

    if (sendChain(data, "DB 3F FF ") != "90 00"):
        return False

    pub = bytearray.fromhex(nStr+eStr)          # Get the public elements of the key
    if (not (putFP(pub, keyType))):
        return False

    if (not (putTime(keyType))):
        return False

    return True


def putData():
    print "\nYou will need to verify the PW3 PIN"
    if (not (verify("83 "))):
        return False

    select = -1
    print "\n\t(9) PUT DATA"
    while True:
        print "Please enter the type of data you would like to put:"
        print "\t(1) Name"
        print "\t(2) Login Data"
        print "\t(3) Language Preferences"
        print "\t(4) Sex"
        print "\t(5) URL"
        print "\t(6) Cardholder Certificate"
        print "\t(7) PW Status Bytes"
        print "\t(8) Resetting Code"
        print "\t(9) Import Key"
        print "\t(0) Back"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            return
        elif (select == 1):
            doPut("name (Max. 39 characters): ", 39, "00 5B ")
        elif (select == 2):
            doPut("login data (Max. 254 characters): ", 254, "00 5E ")
        elif (select == 3):
            doPut("language preferences (Max. 8 characters): ", 8, "5F 2D ")
        elif (select == 4):
            while True:
                inp = raw_input("\nPlease enter the sex (M)ale or (F)emale): ")
                if (inp == "M" or inp == "m" or inp.upper() == "MALE"):
                    sex = "31 "
                    break
                elif (inp == "F" or inp == "f" or inp.upper() == "FEMALE"):
                    sex = "32 "
                    break

            if (sendCommand("00 DA 5F 35 01 " + sex) == "90 00"):
                print "Operation completed successfully\n"
            else:
                print "Operation failed\n"
        elif (select == 5):
            doPut("URL (Max. 254 characters): ", 254, "5F 50 ")
        elif (select == 6):
            doPut("cardholder certificate (Max. 1216 characters): ", 1216, "7F 21 ")
        elif (select == 7):
            while True:
                inp = raw_input("\nPlease enter PW1 status (0 or 1): ")
                if (int(inp) == 0):
                    val = "00 "
                    break
                elif (int(inp) == 1):
                    val = "01 "
                    break

            if (sendCommand("00 DA 00 C4 01 " + val) == "90 00"):
                print "Operation completed successfully\n"
            else:
                print "Operation failed\n"
        elif (select == 8):
            while True:
                print "\nPlease enter the resetting code (RC): "
                while True:
                    pw1 = getpass("Please enter the password (Min. 8 char./Max. 127 char. or empty): ")
                    if (len(pw1) == 0 or (len(pw1) >= 8 and len(pw1) <= 127)):
                        break

                pw2 = getpass("Please confirm the password: ")
                if (pw1 == pw2):
                    break
                else:
                    print "The passwords do not match"

            pStr = " ".join("{0:02x}".format(ord(c)) for c in pw1).upper() + " "
            if (sendCommand("00 DA 00 D3 " + getLen(pStr) + pStr) == "90 00"):
                print "Operation completed successfully\n"
            else:
                print "Operation failed\n"
        elif (select == 9):
            if (importKey()):
                print "The key was imported successfully\n"
            else:
                print "Key import failed\n"
        else:
            print "Invalid option\n"
        select = -1


def handleTerminated():
    print "\n\t(10) TERMINATE"
    select = -1
    while True:
        print "Please enter the type of operation you would like to perform:"
        print "\t(1) ACTIVATE"
        print "\t(0) Back\n"

        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            return
        elif (select == 1):
            if (sendCommand("00 44 00 00 00") == "90 00"):
                print "Operation completed successfully\n"
                return
            else:
                print "Operation failed\n"
        else:
            return
        select = -1


def getByteNumber(mesg):
    while True:
        print mesg
        try:
            number = int(raw_input("Max value: 255, enter 0 to cancel: "))
            if (0 <= number < 256):
                break
            else:
                print "Invalid option\n"
        except ValueError:
            print "Invalid option\n"
    return number


def setPinRetries():
    print "\nYou will need to verify the PW3 PIN"
    if (not (verify("83 "))):
        return False

    print "\n\t(13) SET RETRIES"
    p1 = getByteNumber("Please enter the number of retries for PW1")
    if (p1 == 0):
        return
    rc = getByteNumber("Please enter the number of retries for the resetting code (RC)")
    if (rc == 0):
        return
    p3 = getByteNumber("Please enter the number of retries for PW3")
    if (p3 == 0):
        return
    c = "00 F2 00 00 03" + '{0:02X}'.format(p1) + '{0:02X}'.format(rc) + '{0:02X}'.format(p3) + " "
    if (sendCommand(c) == "90 00"):
        print "\nOperation completed successfully\n"
    else:
        print "\nOperation failed\n"


class handleConnection(SocketServer.BaseRequestHandler):
    def handle(self):
        global command      # The command APDU
        global response     # The response APDU
        global condCommand  # Condition to wait until a new APDU command arrives
        global condResponse # Condition to wait until a response is available
        global newCommand   # Flag for the handler that there is a new command
        global processing   # Flag for the run function that the processing has finished
        global err          # Flag for the run function that an error happened

        with condCommand:
            while (newCommand == 0):
                condCommand.wait()

        with condResponse:
            try:
                self.request.sendall(command)   # Send the command APDU to the ESP32
                response = self.request.recv(257).strip()   # Get the response APDU
            except SocketError:     # ESP32 probably disconnected
                err = 1             # Set the error flag

            processing = 0          # Processing finished, got the response
            newCommand = 0          # Reset the newCommand flag
            condResponse.notify()


if __name__ == '__main__':
    HOST, PORT = '10.42.0.1', 5511

    SocketServer.TCPServer.allow_reuse_address = True
    server = SocketServer.TCPServer((HOST, PORT), handleConnection)
    srvThrd = threading.Thread(target=server.serve_forever)
    srvThrd.daemon = True
    srvThrd.start()

    global command      # The command APDU
    global response     # The response APDU
    global condCommand  # Condition to wait until a new APDU command arrives
    global condResponse # Condition to wait until a response is available
    global newCommand   # Flag for the handler that there is a new command
    global processing   # Flag for the run function that the processing has finished
    global err          # Flag for the run function that an error happened

    condCommand = threading.Condition()
    condResponse = threading.Condition()

    select = -1
    while True:
        newCommand = 0
        processing = 0
        command = ""
        response = ""
        err = 0
        while True:     # Check for terminated status
            if (getARD() == True):
                break

        getLoginData()
        getURL()
        getDSCnt()
        getCRD()

        print "Please enter the type of operation you would like to perform:"
        print "\t (1) VERIFY"
        print "\t (2) CHANGE REFERENCE DATA"
        print "\t (3) RESET RETRY COUNTER"
        print "\t (4) PERFORM SECURITY OPERATION"
        print "\t (5) INTERNAL AUTHENTICATE"
        print "\t (6) GENERATE ASYMMETRIC KEY"
        print "\t (7) GET CHALLENGE"
        print "\t (8) GET DATA"
        print "\t (9) PUT DATA"
        print "\t(10) TERMINATE"
        print "\t(11) ACTIVATE"
        print "\t(12) GET VERSION"
        print "\t(13) SET PIN RETRIES"
        print "\t(0)  QUIT"
        try:
            select = int(raw_input("Your selection: "))
        except ValueError:
            pass

        if (select == 0):
            print "\n\t(0) QUIT\n"
            sys.exit()      # Terminate execution
        elif (select == 1):
            verifySelect()
        elif (select == 2):
            changeReferenceData()
        elif (select == 3):
            resetRetryCounter()
        elif (select == 4):
            performSecOp()
        elif (select == 5):
            intAuth()
        elif (select == 6):
            if (genAsymKey()):
                print "Key generated successfully"
            else:
                print "Key generation failed"
        elif (select == 7):
            getChallenge()
        elif (select == 8):
            getData()
        elif (select == 9):
            putData()
        elif (select == 10):
            if (sendCommand("00 E6 00 00 00") == "90 00"):
                print "Operation completed successfully\n"
            else:
                print "Operation failed\n"
        elif (select == 11):
            print "\n\t(11) ACTIVATE"
            if (sendCommand("00 44 00 00 00") == "90 00"):
                print "Operation completed successfully\n"
            else:
                print "Operation failed\n"
        elif (select == 12):
            print "\n\t(12) GET VERSION"
            resp = sendCommand("00 F1 00 00 00")
            print "Version: " + resp[:len(resp)-6] + "\n"
        elif (select == 13):
            setPinRetries()
        select = -1
