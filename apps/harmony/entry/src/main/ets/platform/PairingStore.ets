import { asset } from '@kit.AssetStoreKit';
import { JSON, url, util } from '@kit.ArkTS';

const HOST_ALIAS: Uint8Array = new util.TextEncoder().encode('vibescreen.trusted-lan-host.v1');
const IDENTITY_ALIAS: Uint8Array = new util.TextEncoder().encode('vibescreen.client-identity.v1');
const RECORD_VERSION: number = 1;
const CLIENT_ID_PATTERN: RegExp = /^harmony-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export interface PairingTarget { host: string; port: number; offerId: string; oneTimeCredential: string; }
export interface TrustedHostRecord { version: number; host: string; port: number; offerId: string; }
interface ClientIdentityRecord { version: number; clientId: string; }
interface DecodedClientIdentity { clientId: string; legacy: boolean; }

export class PairingLink {
  static parse(value: string): PairingTarget {
    const parsed: url.URL = url.URL.parseURL(value.trim());
    if (parsed.protocol !== 'vibescreen:') throw new Error('仅支持 vibescreen:// 配对链接');
    const port: number = Number(parsed.searchParams.get('port'));
    const offerId: string = parsed.searchParams.get('offer') ?? '';
    const credential: string = parsed.searchParams.get('credential') ?? '';
    if (parsed.hostname.length === 0 || !Number.isInteger(port) || port < 1 || port > 65535 || offerId.length === 0 || credential.length === 0) {
      throw new Error('配对链接不完整或已损坏');
    }
    return { host: parsed.hostname, port, offerId, oneTimeCredential: credential };
  }
}

export class PairingStore {
  private static operationTail: Promise<void> = Promise.resolve();

  async saveTrustedHost(target: PairingTarget): Promise<void> {
    // The one-time credential is deliberately not persisted. Full proof exchange remains host-gated.
    const record: TrustedHostRecord = { version: RECORD_VERSION, host: target.host, port: target.port, offerId: target.offerId };
    await this.serialized(async () => {
      await this.upsert(HOST_ALIAS, new util.TextEncoder().encode(JSON.stringify(record)));
    });
  }

  async loadTrustedHost(): Promise<TrustedHostRecord | undefined> {
    return this.serialized(async () => {
      const secret: Uint8Array | undefined = await this.loadSecret(HOST_ALIAS);
      if (secret === undefined) return undefined;
      try {
        const raw = JSON.parse(new util.TextDecoder().decode(secret)) as Partial<TrustedHostRecord>;
        if (raw.version !== RECORD_VERSION || typeof raw.host !== 'string' || raw.host.length === 0 ||
          !Number.isInteger(raw.port) || (raw.port as number) < 1 || (raw.port as number) > 65535 ||
          typeof raw.offerId !== 'string' || raw.offerId.length === 0) {
          throw new Error('unsupported_record');
        }
        return raw as TrustedHostRecord;
      } catch (_error) {
        await this.remove(HOST_ALIAS);
        throw new Error('已保存的主机记录损坏或版本不受支持');
      }
    });
  }

  async clientId(): Promise<string> {
    return this.serialized(async () => {
      const stored: Uint8Array | undefined = await this.loadSecret(IDENTITY_ALIAS);
      if (stored !== undefined) {
        const decoded: DecodedClientIdentity = this.decodeIdentity(stored);
        if (decoded.legacy) {
          const migrated: ClientIdentityRecord = { version: RECORD_VERSION, clientId: decoded.clientId };
          await this.upsert(IDENTITY_ALIAS, new util.TextEncoder().encode(JSON.stringify(migrated)));
        }
        return decoded.clientId;
      }

      const generated: string = `harmony-${util.generateRandomUUID(true)}`;
      const record: ClientIdentityRecord = { version: RECORD_VERSION, clientId: generated };
      const encoded: Uint8Array = new util.TextEncoder().encode(JSON.stringify(record));
      try {
        await this.add(IDENTITY_ALIAS, encoded);
        return generated;
      } catch (error) {
        // Another PairingStore/process may have won the create race. Its identity is authoritative.
        const winner: Uint8Array | undefined = await this.loadSecret(IDENTITY_ALIAS);
        if (winner !== undefined) return this.decodeIdentity(winner).clientId;
        throw error;
      }
    });
  }

  async forgetHost(): Promise<void> {
    await this.serialized(async () => { await this.remove(HOST_ALIAS); });
  }

  private async serialized<T>(operation: () => Promise<T>): Promise<T> {
    const predecessor: Promise<void> = PairingStore.operationTail;
    let release: () => void = () => {};
    PairingStore.operationTail = new Promise<void>((resolve) => { release = resolve; });
    await predecessor;
    try { return await operation(); }
    finally { release(); }
  }

  private async add(alias: Uint8Array, secret: Uint8Array): Promise<void> {
    const attributes: asset.AssetMap = new Map();
    attributes.set(asset.Tag.ALIAS, alias); attributes.set(asset.Tag.SECRET, secret);
    await asset.add(attributes);
  }

  private async upsert(alias: Uint8Array, secret: Uint8Array): Promise<void> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, alias); query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ATTRIBUTES);
    const matches: asset.AssetMap[] = await asset.query(query);
    if (matches.length > 1) throw new Error('Asset Store 中存在重复别名记录');
    if (matches.length === 1) {
      const updateQuery: asset.AssetMap = new Map();
      updateQuery.set(asset.Tag.ALIAS, alias);
      const updates: asset.AssetMap = new Map();
      updates.set(asset.Tag.SECRET, secret);
      await asset.update(updateQuery, updates);
      return;
    }
    try { await this.add(alias, secret); }
    catch (error) {
      const winner: Uint8Array | undefined = await this.loadSecret(alias);
      if (winner === undefined) throw error;
      const updateQuery: asset.AssetMap = new Map();
      updateQuery.set(asset.Tag.ALIAS, alias);
      const updates: asset.AssetMap = new Map();
      updates.set(asset.Tag.SECRET, secret);
      await asset.update(updateQuery, updates);
    }
  }

  private async loadSecret(alias: Uint8Array): Promise<Uint8Array | undefined> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, alias); query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ALL);
    const matches: asset.AssetMap[] = await asset.query(query);
    if (matches.length === 0) return undefined;
    if (matches.length > 1) throw new Error('Asset Store 中存在重复别名记录');
    return matches[0].get(asset.Tag.SECRET) as Uint8Array;
  }

  private async remove(alias: Uint8Array): Promise<void> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, alias); query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ATTRIBUTES);
    const matches: asset.AssetMap[] = await asset.query(query);
    if (matches.length > 0) { const removeQuery: asset.AssetMap = new Map(); removeQuery.set(asset.Tag.ALIAS, alias); await asset.remove(removeQuery); }
  }

  private decodeIdentity(secret: Uint8Array): DecodedClientIdentity {
    try {
      const text: string = new util.TextDecoder().decode(secret);
      if (CLIENT_ID_PATTERN.test(text)) return { clientId: text, legacy: true };
      const raw = JSON.parse(text) as Partial<ClientIdentityRecord>;
      if (raw.version !== RECORD_VERSION || typeof raw.clientId !== 'string' || !CLIENT_ID_PATTERN.test(raw.clientId)) {
        throw new Error('unsupported_identity');
      }
      return { clientId: raw.clientId, legacy: false };
    } catch (_error) {
      throw new Error('已保存的客户端身份损坏或版本不受支持');
    }
  }
}
