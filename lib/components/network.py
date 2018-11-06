#!/usr/bin/python3

import os
import solc
from subprocess import Popen, DEVNULL
import sys
from web3 import Web3, HTTPProvider

from lib.components.config import CONFIG

      

class RPC(Popen):

    def __init__(self, cmd):
        super().__init__(cmd.split(' '), stdout = DEVNULL, stdin = DEVNULL)
    
    def __del__(self):
        self.terminate()

class Network:

    def __init__(self):
        self.accounts = [Account(i) for i in web3.eth.accounts]

    def __getattr__(self, name):
        return getattr(web3, name)
    
    def contract(self, name, address, owner = None):
        interface = next(v for k,v in compiled.items() if k.split(':')[-1] == name)
        return Contract(address, interface['abi'], owner)

    def add_account(self, priv_key):
        acct = web3.eth.account.privateKeyToAccount(priv_key)
        self.accounts.append(LocalAccount(acct.address))
        self.accounts[-1]._acct = acct
        return self.accounts[-1]

class Contract:

    def __init__(self, address, abi, owner):
        self._contract = web3.eth.contract(address = address, abi = abi)
        self.abi = dict((
            i['name'],
            True if i['stateMutability'] in ['view','pure'] else False
            ) for i in abi if i['type']=="function")
        self.owner = owner
    
    def __getattr__(self, name):
        if name not in self.abi:
            return getattr(self._contract, name)
        def _call(*args):
            result = getattr(self._contract.functions,name)(*args).call()
            if type(result) is not list:
                return web3.toHex(result) if type(result) is bytes else result
            return [(web3.toHex(i) if type(i) is bytes else i) for i in result]
        def _tx(*args):
            if type(args[-1]) is dict:
                args, tx = (args[:-1], args[-1])
                if 'from' not in tx:
                    tx['from'] = self.owner
                if 'value' in tx and type(tx['value']) is float:
                    tx['value'] = int(tx['value'])
            else:
                tx = {'from': self.owner}
            fn = getattr(self._contract.functions,name)
            txreceipt = tx['from']._contract_call(fn, args, tx)
            if '--gas' in sys.argv:
                print("{}: {} gas".format(name, txreceipt['gasUsed']))
            return web3.toHex(txreceipt['transactionHash'])
        return _call if self.abi[name] else _tx

    def revert(self,name,*args):
        if name not in self.abi:
            raise AttributeError("{} is not a valid function.".format(name))
        try:
            self.__getattr__(name)(*args)
            return False
        except ValueError:
            return True

class _AccountBase(str):

    def __init__(self, addr):
        self.address = addr

    def __repr__(self):
        return "<Account object '{}'>".format(self.address)

    def __str__(self):
        return self.address
    
    def nonce(self):
        return web3.eth.getTransactionCount(self.address)

    def balance(self):
        return web3.eth.getBalance(self.address)

    def deploy(self, name, *args):
        interface = next(v for k,v in compiled.items() if k.split(':')[-1] == name)
        contract = web3.eth.contract(
            abi = interface['abi'],
            bytecode = interface['bin']
        )
        txreceipt = self._contract_call(contract.constructor, args, {})
        if '--gas' in sys.argv:
            print("deploy {}: {} gas".format(name, txreceipt['gasUsed']))
        contract = Contract(
            txreceipt.contractAddress,
            interface['abi'],
            self
        )
        if not hasattr(self, name):
            setattr(self, name, contract)
        else:
            i = next(i for i in range(1,10000) if not hasattr(self, name+str(i)))
            setattr(self, name+str(i), contract)
        return contract 

class Account(_AccountBase):

    def transfer(self, to, amount, gas_price=None):
        txid = web3.eth.sendTransaction({
            'from': self.address,
            'to': to,
            'value': int(amount),
            'gasPrice': gas_price or web3.eth.gasPrice,
            })
        return web3.toHex(txid)

    def _contract_call(self, fn, args, tx):
        tx['from'] = self.address
        txid = fn(*args).transact(tx)
        return web3.eth.waitForTransactionReceipt(txid)

class LocalAccount(_AccountBase):

    #def __init__(self, priv_key):
    #    self._acct = web3.eth.account.privateKeyToAccount(priv_key)
    #    self.address = self._acct.address

    def transfer(self, to, amount, gas_price=None):
        signed_tx = self._acct.signTransaction({
            'from': self.address,
            'nonce': self.nonce(),
            'gasPrice': gas_price or web3.eth.gasPrice,
            'gas': 21000,
            'to': to,
            'value': int(amount),
            'data': ""
            }).rawTransaction
        txid = web3.eth.sendRawTransaction(signed_tx)
        return web3.toHex(txid)

    def _contract_call(self, fn, args, tx):
        tx.update({
            'from':self.address,
            'nonce':self.nonce(),
            'gasPrice': web3.eth.gasPrice,
            'gas': fn(*args).estimateGas(),
            })
        raw = fn(*args).buildTransaction(tx)
        txid = web3.eth.sendRawTransaction(
            self._acct.signTransaction(raw).rawTransaction)
        return web3.eth.waitForTransactionReceipt(txid)

if '--network' in sys.argv:
    name = sys.argv[sys.argv.index('--network')+1]
    try:
        netconf = CONFIG['networks'][name]
        print("Using network '{}'".format(name))
    except KeyError:
        sys.exit("ERROR: Network '{}' is not defined in config.json".format(name))
else:
    netconf = CONFIG['networks']['development']
    print("Using network 'development'")
if 'test-rpc' in netconf:
    rpc = RPC(netconf['test-rpc'])

contract_files = ["{}/{}".format(i[0],x) for i in os.walk('contracts') for x in i[2]] 
if not contract_files:
    sys.exit("ERROR: Cannot find any .sol files in contracts folder")
print("Compiling contracts...")
compiled = solc.compile_files(contract_files, optimize=CONFIG['solc']['optimize'])

web3 = Web3(HTTPProvider(netconf['host']))