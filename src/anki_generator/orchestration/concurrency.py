"""Bounded independent work with checkpoint-safe interruption and stable ordering."""

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def bounded_map[T, R](
    items: Iterable[T], work: Callable[[T], R], *, workers: int, checkpoint: Callable[[], None]
) -> list[R]:
    values = list(items)
    if workers <= 1:
        result = []
        for value in values:
            checkpoint()
            result.append(work(value))
        return result
    results: dict[int, R] = {}
    iterator = iter(enumerate(values))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="anki-stage") as executor:
        active = {}
        try:
            for _ in range(min(workers, len(values))):
                index, value = next(iterator)
                checkpoint()
                active[executor.submit(work, value)] = index
            while active:
                completed, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed:
                    index = active.pop(future)
                    results[index] = future.result()
                    checkpoint()
                    next_item = next(iterator, None)
                    if next_item is not None:
                        next_index, value = next_item
                        active[executor.submit(work, value)] = next_index
        except BaseException:
            for future in active:
                future.cancel()
            # In-flight calls finish their durable result/checkpoint before the
            # executor closes. No new tasks are dispatched after interruption.
            raise
    return [results[index] for index in range(len(values))]
