package kr.roomax.alerts

import android.content.Context
import androidx.work.*
import java.util.concurrent.TimeUnit

class RetryWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result = try {
        if (Forwarder.flush(applicationContext)) Result.retry() else Result.success()
    } catch (_: Exception) { Result.retry() } // never log secret-bearing exceptions

    companion object {
        fun schedule(ctx: Context) {
            val constraints = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
            val manager = WorkManager.getInstance(ctx)
            manager.enqueueUniqueWork("roomax-send", ExistingWorkPolicy.APPEND_OR_REPLACE,
                OneTimeWorkRequestBuilder<RetryWorker>().setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build())
            // Also prunes expired ciphertext while offline; resumes after reboot/process death.
            manager.enqueueUniquePeriodicWork("roomax-recovery", ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<RetryWorker>(15, TimeUnit.MINUTES).build())
        }
    }
}
