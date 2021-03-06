package ch.ethz.blokcaditapi.storage.chunkentries;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

import static ch.ethz.blokcaditapi.storage.chunkentries.EntryFactory.TYPE_DOUBLE_ENTRY;

/**
 * Created by lukas on 09.05.17.
 */

public final class DoubleEntry implements Entry {

    private final long timestamp;
    private final String metadata;
    private final double dataValue;

    public DoubleEntry(long timestamp, String metadata, Double dataValue) {
        this.timestamp = timestamp;
        this.metadata = metadata;
        this.dataValue = dataValue;
    }

    public long getTimestamp() {
        return timestamp;
    }

    public String getMetadata() {
        return metadata;
    }

    public double getDataValue() {
        return dataValue;
    }

    @Override
    public byte[] encode() {
        int len = this.getEncodedSize();
        ByteBuffer buffer = ByteBuffer.allocate(len);
        buffer.order(ByteOrder.LITTLE_ENDIAN);
        buffer.putInt(len)
                .put((byte) this.getType())
                .putLong(this.timestamp)
                .put(this.metadata.getBytes())
                .putDouble(this.dataValue);
        return buffer.array();
    }

    @Override
    public int getEncodedSize() {
        return Long.SIZE / 8 + Integer.SIZE / 8 + metadata.getBytes().length + Double.SIZE / 8 + 1;
    }

    @Override
    public int getType() {
        return TYPE_DOUBLE_ENTRY;
    }

    @Override
    public void accept(EntryProcessor processor) {
        processor.process(this);
    }

    public static class DoubleEntryDecoder implements EntryDecoder {

        private Entry decodeLocal(ByteBuffer buffer) {
            int lenMeta;
            buffer.order(ByteOrder.LITTLE_ENDIAN);
            int len = buffer.getInt();
            buffer.get();
            long timestamp = buffer.getLong();
            lenMeta = len - Long.SIZE / 8 - Integer.SIZE / 8 - Double.SIZE / 8 - 1;
            byte[] metaDataBytes = new byte[lenMeta];
            buffer.get(metaDataBytes);
            double value = buffer.getDouble();
            return new DoubleEntry(timestamp, new String(metaDataBytes), value);
        }

        @Override
        public Entry decode(byte[] entryBytes) {
            ByteBuffer buffer = ByteBuffer.wrap(entryBytes);
            return decodeLocal(buffer);
        }

        @Override
        public Entry decode(byte[] entryBytes, int offset, int len) {
            ByteBuffer buffer = ByteBuffer.wrap(entryBytes, offset, len);
            return decodeLocal(buffer);
        }
    }
}
