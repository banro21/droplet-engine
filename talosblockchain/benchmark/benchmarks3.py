import base64
import os
import binascii
import threading
from StringIO import StringIO

import boto3
import botocore

from benchmarklogger import FileBenchmarkLogger
from talosdht.util import ENTRY_FETCH_POLICY, ENTRY_STORE_CHECK, ENTRY_CHECK_TOKEN_VALID, ENTRY_GET_AND_CHECK
from talosstorage.checks import get_priv_key, DataStreamIdentifier, BitcoinVersionedPrivateKey, \
    get_and_check_query_token, check_query_token_valid, generate_query_token
from talosstorage.chunkdata import ChunkData, DoubleEntry, create_cloud_chunk, CloudChunk
import time
import random

#########################
# DEFAULT Stream Params #
#########################

# Assumes S3 credentials ar located in ~/.aws/credentials
# (see https://boto3.readthedocs.io/en/latest/guide/quickstart.html)
from talosstorage.storage import TalosStorage
from talosstorage.timebench import TimeKeeper
from talosvc.talosclient.restapiclient import TalosVCRestClient

PRIVATE_KEY = "cN5YgNRq8rbcJwngdp3fRzv833E7Z74TsF8nB6GhzRg8Gd9aGWH1"
NONCE = "OU2HliHRUUZJokNvn84a+A=="
STREAMID = 1
TXID = "8cf71b7ed09acf896b40fc087e56d3d4dbd8cc346a869bb8a81624153c0c2b8c"
IP = "127.0.0.1"
PORT = 14000


def generate_random_chunk(private_key, block_id, stream_identifier, tag="test", key=os.urandom(32),
                          size=1000, max_float=1000):
    chunk = ChunkData()
    for i in range(size):
        entry = DoubleEntry(int(time.time()), tag, random.uniform(0, max_float))
        chunk.add_entry(entry)
    return create_cloud_chunk(stream_identifier, block_id, get_priv_key(private_key), 0, key, chunk)


def create_s3_object():
    return boto3.resource('s3')


def store_data_s3(s3, key, data, bucket_name):
    s3.Object(bucket_name, key).upload_fileobj(StringIO(data))


def get_data_s3(s3, key, bucket_name):
    s3_object = s3.Object(bucket_name, key)
    return s3_object.get()['Body'].read()


def clean_bucket(s3, bucket_name):
    bucket = s3.Bucket(bucket_name)
    for key in bucket.objects.all():
        key.delete()


class TalosS3Storage(TalosStorage):

    def __init__(self, bucket_name):
        self.s3 = create_s3_object()
        self.bucket_name = bucket_name

    def _get_chunk(self, chunk_key):
        return CloudChunk.decode(get_data_s3(self.s3, binascii.hexlify(chunk_key), self.bucket_name))

    def _store_chunk(self, chunk):
        store_data_s3(self.s3,  binascii.hexlify(chunk.key), chunk.encode(), self.bucket_name)


class PlainS3Storage(object):
    def __init__(self, bucket_name):
        self.s3 = create_s3_object()
        self.bucket_name = bucket_name

    def get_chunk(self, chunk_key, time_keeper=TimeKeeper()):
        time_keeper.start_clock()
        chunk = get_data_s3(self.s3, binascii.hexlify(chunk_key), self.bucket_name)
        chunk = CloudChunk.decode(chunk)
        time_keeper.stop_clock("time_s3_get_chunk")
        return chunk

    def store_chunk(self, chunk, time_keeper=TimeKeeper()):
        time_keeper.start_clock()
        store_data_s3(self.s3, binascii.hexlify(chunk.key), chunk.encode(), self.bucket_name)
        time_keeper.stop_clock("time_s3_store_chunk")


def run_benchmark_s3_plain_latency(num_rounds, out_logger, bucket_name, private_key=BitcoinVersionedPrivateKey(PRIVATE_KEY),
                            policy_nonce=base64.b64decode(NONCE), stream_id=STREAMID,
                            txid=TXID, chunk_size=100000):
    key = os.urandom(32)
    identifier = DataStreamIdentifier(private_key.public_key().address(), stream_id, policy_nonce, txid)
    storage = PlainS3Storage(bucket_name)
    for round_bench in range(num_rounds):
        try:
            time_keeper = TimeKeeper()
            chunk = generate_random_chunk(private_key, round_bench, identifier, key=key, size=chunk_size)
            storage.store_chunk(chunk, time_keeper=time_keeper)
            chunk = storage.get_chunk(chunk.key, time_keeper=time_keeper)
            if chunk is None:
                print "Round %d error" % round_bench
            else:
                print "Round %d ok Chunk size: %d" % (round_bench, len(chunk.encode()))

            out_logger.log_times_keeper(time_keeper)
        except Exception as e:
            print "Round %d error: %s" % (round_bench, e)
    print "DONE"
    clean_bucket(storage.s3, bucket_name)


def store_chunk(storage, vc_client, chunk, time_keeper=TimeKeeper()):
    global_id = time_keeper.start_clock_unique()
    time_keeper.start_clock()
    policy = vc_client.get_policy_with_txid(chunk.get_tag_hex())
    time_keeper.stop_clock(ENTRY_FETCH_POLICY)

    store_check_id = time_keeper.start_clock_unique()
    storage.store_check_chunk(chunk, None, policy, time_keeper=TimeKeeper())
    time_keeper.stop_clock_unique(ENTRY_STORE_CHECK, store_check_id)

    time_keeper.stop_clock_unique("time_s3_store_chunk", global_id)


def fetch_chunk(storage, vc_client, token, time_keeper=TimeKeeper()):
    global_id = time_keeper.start_clock_unique()
    time_keeper.start_clock()
    check_query_token_valid(token)
    time_keeper.stop_clock(ENTRY_CHECK_TOKEN_VALID)

    time_keeper.start_clock()
    policy = vc_client.get_policy(token.owner, token.streamid)
    time_keeper.stop_clock(ENTRY_FETCH_POLICY)

    id = time_keeper.start_clock_unique()
    chunk = storage.get_check_chunk(token.chunk_key, token.pubkey, policy, time_keeper=time_keeper)
    time_keeper.stop_clock_unique(ENTRY_GET_AND_CHECK, id)
    time_keeper.stop_clock_unique("time_s3_get_chunk", global_id)
    return chunk


def run_benchmark_s3_talos(num_rounds, out_logger, bucket_name, private_key=BitcoinVersionedPrivateKey(PRIVATE_KEY),
                            policy_nonce=base64.b64decode(NONCE), stream_id=STREAMID,
                            txid=TXID, chunk_size=100000):
    key = os.urandom(32)
    owner = private_key.public_key().address()
    identifier = DataStreamIdentifier(owner, stream_id, policy_nonce, txid)
    vc_client = TalosVCRestClient()
    storage = TalosS3Storage(bucket_name)

    for round_bench in range(num_rounds):
        try:
            time_keeper = TimeKeeper()
            chunk = generate_random_chunk(private_key, round_bench, identifier, key=key, size=chunk_size)
            store_chunk(storage, vc_client, chunk, time_keeper=time_keeper)

            token = generate_query_token(owner, stream_id, os.urandom(16), chunk.key, private_key)
            chunk = fetch_chunk(storage, vc_client, token, time_keeper=time_keeper)

            if chunk is None:
                print "Round %d error" % round_bench
            else:
                print "Round %d ok Chunk size: %d" % (round_bench, len(chunk.encode()))

            out_logger.log_times_keeper(time_keeper)
        except Exception as e:
            print "Round %d error: %s" % (round_bench, e)
    print "DONE"
    clean_bucket(storage.s3, bucket_name)


def splitting(l, n):
    mod = len(l) % n
    size = len(l) / n
    offset = 0
    for i in xrange(0, len(l) - mod, size):
        if i / size < mod:
            yield l[i + offset:i + offset + size + 1]
            offset += 1
        else:
            yield l[i + offset:i + size + offset]


class FetchPlainThread(threading.Thread):
    def __init__(self, my_id, result_store, storage,
                 blockids, private_key, stream_identifier, vc_client, time_keeper=TimeKeeper()):
        self.vc_client = vc_client
        self.time_keeper = time_keeper
        self.stream_identifier = stream_identifier
        self.blockids = blockids
        self.connection = storage
        self.result_store = result_store
        self.my_id = my_id
        self.private_key = private_key
        threading.Thread.__init__(self)

    def run(self):
        for block_id in self.blockids:
            try:
                key = self.stream_identifier.get_key_for_blockid(block_id)
                token = generate_query_token(self.stream_identifier.owner, self.stream_identifier.streamid, os.urandom(16), key, self.private_key)
                chunk = fetch_chunk(self.connection, self.vc_client, token)
                self.result_store[self.my_id].append(chunk)
            except Exception:
                self.result_store[self.my_id].append(None)
                continue


def run_benchmark_s3_plain_fetch(num_rounds, num_gets, out_logger, bucket_name, private_key=BitcoinVersionedPrivateKey(PRIVATE_KEY),
                            policy_nonce=base64.b64decode(NONCE), stream_id=STREAMID,
                            txid=TXID, chunk_size=100000, num_threads=None):
    key = os.urandom(32)
    owner = private_key.public_key().address()
    identifier = DataStreamIdentifier(owner, stream_id, policy_nonce, txid)
    vc_client = TalosVCRestClient()
    storage = TalosS3Storage(bucket_name)

    num_threads = num_threads or num_gets
    print "Store in S3"
    for iter in range(num_gets):
        chunk = generate_random_chunk(private_key, iter, identifier, key=key, size=chunk_size)
        store_chunk(storage, vc_client, chunk)

    for round in range(num_rounds):
        try:
            time_keeper = TimeKeeper()
            results = [[]] * num_threads
            threads = [FetchPlainThread(idx, results, TalosS3Storage(bucket_name), block_id, private_key, identifier, vc_client)
                       for idx, block_id in enumerate(splitting(range(num_gets), num_threads))]
            time_keeper.start_clock()
            map(lambda x: x.start(), threads)
            map(lambda x: x.join(), threads)
            time_keeper.stop_clock("time_fetch_all")
            chunks = [item for sublist in results for item in sublist]
            if len(chunks) == num_gets:
                print "Round %d ok Num results: %d" % (round, num_gets)
            else:
                print "Round %d ok Num results: %d" % (round, num_gets)
            out_logger.log_times_keeper(time_keeper)
        except Exception as e:
            print "Round %d error: %s" % (round, e)
    print "DONE"
    clean_bucket(storage.s3, bucket_name)






#FIELDS_PLAIN = ["time_s3_store_chunk", "time_s3_get_chunk"]
#FIELDS_TALOS = ["time_s3_store_chunk", "time_s3_get_chunk"]
#run_benchmark_s3_talos(100, FileBenchmarkLogger("log.log", FIELDS_PLAIN), "talosblockchain")
run_benchmark_s3_plain_fetch(10, 100, FileBenchmarkLogger("log.log", ['time_fetch_all']), "talosblockchain", num_threads=20)