package dev.telemachus.display

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import java.io.FileNotFoundException
import java.util.concurrent.atomic.AtomicInteger

class ShareFileIntentTestProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun getType(uri: Uri): String {
        getTypeCount.incrementAndGet()
        return "application/octet-stream"
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? {
        queryCount.incrementAndGet()
        return null
    }

    override fun openFile(
        uri: Uri,
        mode: String,
    ): ParcelFileDescriptor {
        openFileCount.incrementAndGet()
        throw FileNotFoundException(uri.toString())
    }

    override fun insert(
        uri: Uri,
        values: ContentValues?,
    ): Uri? = null

    override fun delete(
        uri: Uri,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    companion object {
        val uri: Uri = Uri.parse("content://dev.telemachus.display.sharefiletest/source.bin")
        val queryCount = AtomicInteger()
        val openFileCount = AtomicInteger()
        val getTypeCount = AtomicInteger()

        fun reset() {
            queryCount.set(0)
            openFileCount.set(0)
            getTypeCount.set(0)
        }
    }
}
