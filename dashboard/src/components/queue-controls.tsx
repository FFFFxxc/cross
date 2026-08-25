"use client";

export function QueueControls({
  params,
  onChange,
}: {
  params: URLSearchParams;
  onChange: (name: string, value: string) => void;
}) {
  return (
    <div className="queue-controls">
      <label>
        Сортировка
        <select value={params.get("sort") || "score"} onChange={(event) => onChange("sort", event.target.value)}>
          <option value="newest">Сначала новые</option>
          <option value="reactions">По реакциям</option>
          <option value="views">По просмотрам</option>
          <option value="score">Умный рейтинг</option>
        </select>
      </label>
      <label>
        Тип
        <select value={params.get("media") || "any"} onChange={(event) => onChange("media", event.target.value)}>
          <option value="any">Все</option>
          <option value="video">Видео</option>
          <option value="image">Картинки</option>
        </select>
      </label>
      <label>
        Статус
        <select value={params.get("status") || "pending"} onChange={(event) => onChange("status", event.target.value)}>
          <option value="pending">В очереди</option>
          <option value="processing">Публикуется</option>
          <option value="published">Опубликовано</option>
          <option value="failed">Ошибка</option>
          <option value="ambiguous">Нужна проверка</option>
          <option value="skipped">Пропущено</option>
          <option value="expired">Устарело</option>
          <option value="candidate">Все кандидаты</option>
        </select>
      </label>
      <label>
        Источник
        <input value={params.get("source") || ""} onChange={(event) => onChange("source", event.target.value)} placeholder="Все источники" />
      </label>
    </div>
  );
}
