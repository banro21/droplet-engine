import struct
import zlib
import os
import hashlib
import base64
from binascii import unhexlify, hexlify
from pylepton.lepton import *

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from talosstorage.timebench import TimeKeeper


def compress_data(data, level=6):
    return zlib.compress(data, level)


def decompress_data(data):
    return zlib.decompress(data)


def encrypt_aes_gcm_data(key, plain_data, data):
    iv = os.urandom(12)
    encryptor = Cipher(
        algorithms.AES(key),
        modes.GCM(iv),
        backend=default_backend()
    ).encryptor()
    encryptor.authenticate_additional_data(plain_data)
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return iv + ciphertext, encryptor.tag


def decrypt_aes_gcm_data(key, tag, plain_data, data):
    iv = data[0:12]
    ciphertext = data[12:]

    decryptor = Cipher(
        algorithms.AES(key),
        modes.GCM(iv, tag),
        backend=default_backend()
    ).decryptor()
    decryptor.authenticate_additional_data(plain_data)
    return decryptor.update(ciphertext) + decryptor.finalize()


def hash_sign_data(private_key, data):
    signer = private_key.signer(ec.ECDSA(hashes.SHA256()))
    signer.update(data)
    return signer.finalize()


def check_signed_data(public_key, signature, data):
    verifier = public_key.verifier(signature, ec.ECDSA(hashes.SHA256()))
    verifier.update(data)
    return verifier.verify()

TYPE_DOUBLE_ENTRY = 0
TYPE_PICTURE_ENTRY = 1


class Entry(object):
    def get_type_id(self):
        pass

    def encode(self):
        pass

    def decode(self):
        pass

    def get_encoded_size(self):
        pass


class PictureEntry(Entry):
    def __init__(self, timestamp, metadata, picture_jpg_data, time_keeper=TimeKeeper(), use_compression=False):
        self.timestamp = timestamp
        self.metadata = metadata
        self.picture_data = picture_jpg_data
        self.time_keeper = time_keeper
        self.use_compression = use_compression
        Entry.__init__(self)

    def get_type_id(self):
        return TYPE_PICTURE_ENTRY

    def get_encoded_size(self):
        return struct.calcsize("IQI") + len(self.metadata) + len(self.picture_data)

    def get_encoded_size_compressed(self, compressed_len):
        return struct.calcsize("IQI") + len(self.metadata) + compressed_len

    def encode(self):

        if self.use_compression:
            self.time_keeper.start_clock()
            compressed_picture = compress_jpg_data(self.picture_data)
            self.time_keeper.stop_clock("time_lepton_compression")
            total_size = self.get_encoded_size_compressed(len(compressed_picture))
        else:
            compressed_picture = self.picture_data
            total_size = self.get_encoded_size_compressed(len(compressed_picture))
        return struct.pack("IQI", total_size, self.timestamp, len(self.metadata)) + self.metadata + compressed_picture

    def __str__(self):
        return "%s %s" % (str(self.timestamp), self.metadata)

    @staticmethod
    def decode(encoded, use_decompression=False):
        len_struct = struct.calcsize("IQI")
        len_tot, timestamp, len_meta = struct.unpack("IQI", encoded[:len_struct])
        metadata = encoded[len_struct:(len_struct+len_meta)]
        value = encoded[(len_struct+len_meta):]
        if(use_decompression):
            decompressed_data = decompress_jpg_data(value)
        else:
            decompressed_data = value
        return PictureEntry(timestamp, metadata, decompressed_data)


class DoubleEntry(Entry):
    def __init__(self, timestamp, metadata, value):
        self.timestamp = timestamp
        self.metadata = metadata
        self.value = value
        Entry.__init__(self)

    def get_type_id(self):
        return TYPE_DOUBLE_ENTRY

    def get_encoded_size(self):
        return struct.calcsize("IQ") + len(self.metadata) + struct.calcsize("d")

    def encode(self):
        total_size = self.get_encoded_size()
        return struct.pack("IQ", total_size, self.timestamp) + self.metadata + struct.pack("d", self.value)

    def __str__(self):
        return "%s %s %s" % (str(self.timestamp), self.metadata, str(self.value))

    @staticmethod
    def decode(encoded):
        len_struct = struct.calcsize("IQ")
        len_tot, timestamp = struct.unpack("IQ", encoded[:len_struct])
        len_meta = len_tot - len_struct - struct.calcsize("d")
        metadata = encoded[len_struct:(len_struct+len_meta)]
        value, = struct.unpack("d", encoded[(len_struct+len_meta):])
        return DoubleEntry(timestamp, metadata, value)

DECODER_FOR_TYPE = {
    TYPE_DOUBLE_ENTRY: DoubleEntry.decode,
    TYPE_PICTURE_ENTRY: PictureEntry.decode
}


class ChunkData:
    def __init__(self, entries_in=None, max_size=1000, type=TYPE_DOUBLE_ENTRY):
        self.entries = entries_in or []
        self.max_size = max_size
        self.type = type

    def add_entry(self, entry):
        assert entry.get_type_id() == self.type
        if len(self.entries) >= self.max_size:
            return False
        self.entries.append(entry)
        return True

    def num_entries(self):
        return len(self.entries)

    def __iter__(self):
        for x in self.entries:
            yield x

    def remaining_space(self):
        return self.max_size - len(self.entries)

    def encode(self):
        res = ""
        for entry in self.entries:
            res += entry.encode()
        return struct.pack("B", self.type) + res

    @staticmethod
    def decode(encoded):
        """
        Assumes: |len_entry (4 byte)|encoded entry|
        """
        len_encoded = len(encoded)
        len_integer = struct.calcsize("I")
        type_entry, = struct.unpack("B", encoded[:1])
        cur_pos = 1
        entries = []
        entry_decoder = DECODER_FOR_TYPE[int(type_entry)]
        while cur_pos < len_encoded:
            len_entry, = struct.unpack("I", encoded[cur_pos:(cur_pos+len_integer)])
            entries.append(entry_decoder(encoded[cur_pos:(cur_pos+len_entry)]))
            cur_pos += len_entry
        return ChunkData(entries_in=entries, max_size=len(entries), type=int(type_entry))


class DataStreamIdentifier:
    def __init__(self, owner, streamid, nonce, txid_create_policy):
        self.owner = owner
        self.streamid = streamid
        self.nonce = nonce
        self.txid_create_policy = txid_create_policy

    def get_tag(self):
        return unhexlify(self.txid_create_policy)

    def get_key_for_blockid(self, block_id):
        hasher = hashlib.sha256()
        hasher.update(self.owner)
        hasher.update(str(self.streamid))
        hasher.update(self.nonce)
        hasher.update(str(block_id))
        return hasher.digest()


HASH_BYTES = 32
VERSION_BYTES = 4
MAC_BYTES = 16


def _encode_cloud_chunk_public_part(lookup_key, key_version, policy_tag):
    return lookup_key + struct.pack("I", key_version) + policy_tag


def _enocde_cloud_chunk_without_signature(lookup_key, key_version, policy_tag, encrypted_data, mac_tag):
    return _encode_cloud_chunk_public_part(lookup_key, key_version, policy_tag) + \
               struct.pack("I",  len(encrypted_data)) + encrypted_data + \
               mac_tag


class CloudChunk:
    """
        Key = H(Owner-addr  Stream-id  nonce  blockid) 32 bytes
        Symmetric Key-Version (to know which key version to use ) 4 bytes
        Policy-TAG = Create_txt_id
        Len-Chunk + Encrypted Chunk (symmetric Key Ki) X bytes
        MAC (symmetric Key Ki) 16 bytes
        Signature (Public-Key of Owner) X bytes
    """
    def __init__(self, lookup_key, key_version, policy_tag, encrypted_data, mac_tag, signature):
        self.key = lookup_key
        self.key_version = key_version
        self.policy_tag = policy_tag
        self.encrypted_data = encrypted_data
        self.mac_tag = mac_tag
        self.signature = signature

    def get_and_check_chunk_data(self, symmetric_key, compression_used=True, entry_decoder=DoubleEntry.decode):
        pub_part = _encode_cloud_chunk_public_part(self.key, self.key_version, self.policy_tag)
        data = decrypt_aes_gcm_data(symmetric_key, self.mac_tag, pub_part, self.encrypted_data)
        if compression_used:
            data = decompress_data(data)
        return ChunkData.decode(data, entry_decoder=entry_decoder)

    def check_signature(self, public_key):
        data = _enocde_cloud_chunk_without_signature(self.key, self.key_version,
                                                     self.policy_tag, self.encrypted_data, self.mac_tag)
        return check_signed_data(public_key, self.signature, data)

    def get_encoded_len(self):
        return struct.calcsize("I") + 2*HASH_BYTES + VERSION_BYTES + MAC_BYTES + \
               len(self.signature) + len(self.encrypted_data)

    def encode(self):
        return _enocde_cloud_chunk_without_signature(self.key, self.key_version,
                                                     self.policy_tag, self.encrypted_data, self.mac_tag) \
                + self.signature

    def get_encoded_without_key(self):
        return self.encode()[HASH_BYTES:]

    def get_tag_hex(self):
        return hexlify(self.policy_tag)

    def get_key_hex(self):
        return hexlify(self.key)

    def get_base64_encoded(self):
        return base64.b64encode(self.encode())

    @staticmethod
    def decode(encoded):
        cur_pos = 0
        len_int = struct.calcsize("I")
        key = encoded[:HASH_BYTES]
        cur_pos += HASH_BYTES
        key_version, = struct.unpack("I", encoded[cur_pos:(cur_pos+VERSION_BYTES)])
        cur_pos += VERSION_BYTES
        policy_tag = encoded[cur_pos:(cur_pos+HASH_BYTES)]
        cur_pos += HASH_BYTES
        enc_len, = struct.unpack("I", encoded[cur_pos:(cur_pos+len_int)])
        cur_pos += len_int
        encrypted_data = encoded[cur_pos:(cur_pos+enc_len)]
        cur_pos += enc_len
        mac_tag = encoded[cur_pos:(cur_pos+MAC_BYTES)]
        cur_pos += MAC_BYTES
        signature = encoded[cur_pos:]
        return CloudChunk(key, key_version, policy_tag, encrypted_data, mac_tag, signature)

    @staticmethod
    def decode_base64_str(encoded):
        return CloudChunk.decode(base64.b64decode(encoded))


def create_cloud_chunk(data_stream_identifier, block_id, private_key, key_version,
                       symmetric_key, chunk_data, use_compression=True, time_keeper=TimeKeeper()):
    data = chunk_data.encode()
    if use_compression:
        time_keeper.start_clock()
        data = compress_data(data)
        time_keeper.stop_clock('chunk_compression')
    block_key = data_stream_identifier.get_key_for_blockid(block_id)
    tag = data_stream_identifier.get_tag()

    time_keeper.start_clock()
    encrypted_data, mac_tag = encrypt_aes_gcm_data(symmetric_key,
                                                   _encode_cloud_chunk_public_part(block_key, key_version, tag), data)
    time_keeper.stop_clock('gcm_encryption')

    time_keeper.start_clock()
    signature = hash_sign_data(private_key,
                               _enocde_cloud_chunk_without_signature(block_key, key_version,
                                                                     tag, encrypted_data, mac_tag))
    time_keeper.stop_clock('ecdsa_signature')
    return CloudChunk(block_key, key_version, tag, encrypted_data, mac_tag, signature)


def get_chunk_data_from_cloud_chunk(cloud_chunk, symmetric_key, is_compressed=True):
    pub_part = _encode_cloud_chunk_public_part(cloud_chunk.key, cloud_chunk.key_version, cloud_chunk.policy_tag)
    data = decrypt_aes_gcm_data(symmetric_key, cloud_chunk.mac_tag, pub_part, cloud_chunk.encrypted_data)
    if is_compressed:
        data = decompress_data(data)
    return ChunkData.decode(data)