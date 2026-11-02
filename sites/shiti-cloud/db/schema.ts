import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const studyDocuments = sqliteTable('study_documents', { key:text('key').primaryKey(),payload:text('payload').notNull() });
export const studyRevision = sqliteTable('study_revision', { id:integer('id').primaryKey(), revision:integer('revision').notNull().default(0), initialized:integer('initialized').notNull().default(0) });
